"""OpenElectricity (OpenNEM) fetcher — orchestration layer, schema v1.0.

Fetches the live NEM and WEM data from the OpenElectricity public API.
The returned documents conform to `raw.openelectricity_mix` v1.0 and
`raw.openelectricity_facilities` v1.0.

Concurrency: every (network, metric) pair is fetched in its own task
via `client.py`'s `OpenElectricityClient`; failures on one network or
metric don't kill the others. Once all metrics for a network are back,
`transformers.py` merges them into one canonical document per (ts,
region).

Schema v1.0 design notes (v1.0 → v0.3 deltas below):

  • Coal is DISAGGREGATED into coal_black_mw + coal_brown_mw
      Rationale: black and brown coal have very different emissions
      intensities (≈0.85 vs ≈1.10 kgCO2e/MWh) and prices. Aggregating
      them silently into a single coal_mw makes the emissions calc
      inaccurate. WEM is ~100% black coal, but NEM has both (Vic is
      brown-coal dominated).

  • Gas is DISAGGREGATED into gas_ccgt_mw, gas_ocgt_mw, gas_other_mw
      Rationale: CCGT is baseload (heat rate ~7 GJ/MWh, low marginal
      cost), OCGT is peaker (~12 GJ/MWh, high marginal cost). Price
      response and bidding behaviour are completely different. The
      other three sub-types (gas_recip, gas_steam, gas_wcmg) are
      aggregated into gas_other_mw — they have small capacity and
      behave more like OCGT than CCGT.

  • Bioenergy is AGGREGATED into biomass_mw (biogas + biomass)
      Rationale: <1% of generation, similar bidding behaviour, low
      analytical value of the split.

  • `status` was renamed to `data_quality_status`
      Values: "forecast" | "realtime" | "preliminary" | "final" |
              "revised" | "unknown"
      Rationale: ML backtests must not train on realtime data — the
      5-min dispatch numbers get revised for up to 36 months as AEMO
      re-settles. Filter to data_quality_status="final" before
      training the LSTM.

  • `flow_imports_mw` / `flow_exports_mw` were renamed to
    `interconnector_imports_mw` / `interconnector_exports_mw`
      Rationale: WEM is currently islanded but is planning interconnectors
      (SWIS expansion, potential link to NEM). Keeping the columns
      present (null/0 for WEM) makes the schema future-proof — no code
      change needed when WEM interconnectors come online.

  • `schema_version: "1.0"` added to every document
      Rationale: when you add hydrogen or long-duration storage in
      v1.1, you can detect the change and migrate in dbt.

  • `market_value` added to the Market domain
      Rationale: total $ value of dispatched energy in the interval
      (price_mwh × demand_mw × interval_hours). Useful for revenue
      analysis; would otherwise require a join.

Usage:
    # Network fetcher (every 5 minutes)
    fetcher = OpenElectricityFetcher(api_key=settings.oe_api_key)
    async with httpx.AsyncClient() as client:
        docs = await fetcher.fetch(
            client,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        await bulk_upsert(db, "openelectricity_responses", docs,
                          unique_keys=("network_code", "ts"))

    # Facility registry (monthly)
    facility_fetcher = OpenElectricityFacilityFetcher(api_key=settings.oe_api_key)
    facilities = await facility_fetcher.fetch_facilities(client)
    await bulk_upsert(db, "openelectricity_facilities", facilities,
                      unique_keys=("facility_id",))
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from ecolens.config import get_settings
from ecolens.ingestion.circuit_breaker import CircuitBreaker
from ecolens.shared.observability.logging import get_logger

from .client import OpenElectricityClient
from .schema import DEFAULT_METRICS, NETWORK_CAPABILITIES, SCHEMA_VERSION
from .transformers import diagnose_data_quality, merge_network

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════
# Network-level fetcher
# ════════════════════════════════════════════════════════════════════
class OpenElectricityFetcher:
    """Fetcher for the OpenElectricity v4 network-data API.

    Responsible for:
      1. Building the job list — every (network, metric) pair the
         network actually supports (see NETWORK_CAPABILITIES).
      2. Fetching each job concurrently via `OpenElectricityClient`
         (SDK preferred, httpx fallback); one failure doesn't abort
         the others.
      3. Handing each network's collected per-metric frames to
         `transformers.merge_network` for reshaping into the v1.0
         canonical schema.
      4. Running WEM/NEM data-quality diagnostics on the result.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        use_sdk: bool = True,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.oe_api_key
        self._client = OpenElectricityClient(
            self.api_key, use_sdk=use_sdk, circuit_breaker=circuit_breaker
        )

    # ──────────────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────────────
    async def fetch(
        self,
        client: httpx.AsyncClient,
        since: datetime | None = None,
        until: datetime | None = None,
        networks: list[str] | None = None,
        *,
        metrics: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch OE for every (network × metric) and return merged docs."""
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(minutes=30)
        if until is None:
            until = datetime.now(timezone.utc)
        if networks is None:
            networks = ["NEM", "WEM"]
        if metrics is None:
            metrics = list(DEFAULT_METRICS)

        # Build the job list, respecting per-network capabilities
        jobs: list[tuple[str, str]] = []
        for network in networks:
            caps = NETWORK_CAPABILITIES.get(network, {})
            for metric in metrics:
                if caps.get(metric, True):
                    jobs.append((network, metric))
                else:
                    log.debug(
                        "oe.fetcher.skip_unsupported", network=network, metric=metric
                    )

        # Fetch every (network, metric) concurrently
        coros = [
            self._safe_fetch_metric(client, net, metric, since, until)
            for net, metric in jobs
        ]
        results = await asyncio.gather(*coros, return_exceptions=False)

        # Bucket the frames by network
        per_network: dict[str, dict[str, pd.DataFrame]] = {}
        for network, metric, df in results:
            per_network.setdefault(network, {})[metric] = df

        # Merge each network's metrics on (ts, region) — pure pandas,
        # no I/O, so no need to gather these as coroutines.
        merged = [
            merge_network(network, frames, since)
            for network, frames in per_network.items()
        ]
        docs: list[dict[str, Any]] = []
        for df in merged:
            if df is not None and not df.empty:
                diagnose_data_quality(df)
                docs.extend(df.to_dict("records"))
        log.info(
            "oe.fetcher.complete",
            rows=len(docs),
            networks=list(per_network.keys()),
            metrics=metrics,
            schema_version=SCHEMA_VERSION,
        )
        return docs

    # ──────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────
    async def _safe_fetch_metric(
        self,
        client: httpx.AsyncClient,
        network: str,
        metric: str,
        since: datetime,
        until: datetime,
    ) -> tuple[str, str, pd.DataFrame | None]:
        try:
            df = await self._client.fetch_metric(client, network, metric, since, until)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "oe.fetcher.metric_failed",
                network=network,
                metric=metric,
                error=str(exc),
            )
            df = None
        return network, metric, df


# ════════════════════════════════════════════════════════════════════
# Facility registry fetcher (also v1.0)
# ════════════════════════════════════════════════════════════════════
class OpenElectricityFacilityFetcher:
    """Fetcher for the OpenElectricity facility registry (v1.0).

    The endpoint is `GET /v4/facilities/{network}` and returns a list
    of facility records. Each record is one row in MongoDB keyed by
    `facility_id` (a code like "BAYSW1" for Bayswater Unit 1).
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.oe_api_key
        self._client = OpenElectricityClient(
            self.api_key, use_sdk=False, circuit_breaker=circuit_breaker
        )

    async def fetch_facilities(
        self,
        client: httpx.AsyncClient,
        networks: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if networks is None:
            networks = ["NEM", "WEM"]
        coros = [self._safe_fetch_facilities(client, net) for net in networks]
        results = await asyncio.gather(*coros)
        docs: list[dict[str, Any]] = []
        for df in results:
            if df is not None and not df.empty:
                docs.extend(df.to_dict("records"))
        log.info(
            "oe.facilities.complete",
            facilities=len(docs),
            networks=networks,
            schema_version=SCHEMA_VERSION,
        )
        return docs

    async def _safe_fetch_facilities(
        self,
        client: httpx.AsyncClient,
        network: str,
    ) -> pd.DataFrame | None:
        try:
            return await self._client.fetch_facilities_raw(client, network)
        except Exception as exc:  # noqa: BLE001
            log.error("oe.facilities.failed", network=network, error=str(exc))
            return None
