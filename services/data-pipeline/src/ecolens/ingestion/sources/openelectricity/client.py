"""HTTP/SDK client for the OpenElectricity v4 API.

Owns all network I/O: hits the API (SDK preferred, httpx fallback) and
decodes the wire response into long-form pandas DataFrames — one row
per (ts, [fuel,] value). Does NOT merge or reshape across metrics into
the final canonical document; see `transformers.py` for that.

Retries (`ingest_max_retries`/`ingest_retry_backoff_base`) wrap the
HTTP fallback path only -- the SDK path already has its own
try/except-then-fall-back-to-HTTP, so retrying it too would just delay
that fallback. Circuit breaker protection (optional, see ECO-101)
wraps the whole `fetch_metric` call.
"""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from ecolens.ingestion.circuit_breaker import CircuitBreaker, retry_with_backoff
from ecolens.ingestion.storage.settings import MongoSettings, get_mongo_settings
from ecolens.shared.observability.logging import get_logger

from .schema import (
    METRIC_API_NAME,
    METRIC_ENDPOINT,
    NETWORK_UTC_OFFSET_HOURS,
    SCHEMA_VERSION,
)
from .transformers import normalize_data_quality

log = get_logger(__name__)


class OpenElectricityClient:
    """Fetch one (network, metric) or one network's facility list at a time.

    Two fetch strategies for metrics:
      1. Official `openelectricity` Python SDK (preferred).
      2. Direct httpx call to the OE REST v4 API (fallback when the
         SDK isn't importable or errors).
    """

    # Two distinct endpoints — see METRIC_ENDPOINT in schema.py for
    # which metric goes where (confirmed against the real API's
    # openapi.json, not assumed from naming).
    DATA_BASE_URL = "https://api.openelectricity.org.au/v4/data/network"
    MARKET_BASE_URL = "https://api.openelectricity.org.au/v4/market/network"
    FACILITY_BASE_URL = "https://api.openelectricity.org.au/v4/facilities"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        use_sdk: bool = True,
        settings: MongoSettings | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.api_key = api_key
        self.use_sdk = use_sdk and (
            importlib.util.find_spec("openelectricity") is not None
        )
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if not self.headers:
            log.warning("oe.client.no_api_key", note="Requests will likely 401.")
        settings = settings or get_mongo_settings()
        self.max_retries = settings.ingest_max_retries
        self.backoff_base = settings.ingest_retry_backoff_base
        self.circuit_breaker = circuit_breaker

    # ──────────────────────────────────────────────────────────────
    # Network metrics
    # ──────────────────────────────────────────────────────────────
    async def fetch_metric(
        self,
        client: httpx.AsyncClient,
        network: str,
        metric: str,
        since: datetime,
        until: datetime,
    ) -> pd.DataFrame:
        async def _impl() -> pd.DataFrame:
            if self.use_sdk:
                df = await self._fetch_with_sdk(network, metric, since, until)
                if df is not None:
                    return df
                log.warning("oe.sdk.fallback_to_http", network=network, metric=metric)
            return await self._fetch_with_http(client, network, metric, since, until)

        if self.circuit_breaker is not None:
            return await self.circuit_breaker.call(_impl)
        return await _impl()

    async def _fetch_with_sdk(
        self,
        network: str,
        metric: str,
        since: datetime,
        until: datetime,
    ) -> pd.DataFrame | None:
        try:
            from openelectricity import OEClient  # type: ignore
        except ImportError:
            return None
        try:
            sdk_client = OEClient(api_key=self.api_key)
            offset = NETWORK_UTC_OFFSET_HOURS[network]
            local_since = (
                since.astimezone(timezone.utc) + timedelta(hours=offset)
            ).replace(tzinfo=None)
            local_until = (
                until.astimezone(timezone.utc) + timedelta(hours=offset)
            ).replace(tzinfo=None)
            kwargs: dict[str, Any] = {
                "network": network,
                "metrics": [metric],
                "interval": "5m",
                "date_start": local_since,
                "date_end": local_until,
            }
            if metric in ("power", "curtailment"):
                kwargs["secondary_grouping"] = "fueltech"
            df = await asyncio.to_thread(sdk_client.get_network_data, **kwargs)
            if df is None or (hasattr(df, "empty") and df.empty):
                return None
            return self._reshape_sdk_response(df, network, metric)
        except Exception as exc:  # noqa: BLE001
            log.warning("oe.sdk.error", network=network, metric=metric, error=str(exc))
            return None

    def _reshape_sdk_response(
        self, df: pd.DataFrame, network: str, metric: str
    ) -> pd.DataFrame:
        if metric == "power":
            long = (
                df.reset_index()
                .melt(
                    id_vars=df.index.name or "ts",
                    var_name="fuel",
                    value_name="mw",
                )
                .rename(columns={df.index.name or "ts": "ts"})
            )
            long["region"] = network
            return long[["ts", "region", "fuel", "mw"]]
        if metric == "curtailment":
            long = (
                df.reset_index()
                .melt(
                    id_vars=df.index.name or "ts",
                    var_name="fuel",
                    value_name="curtailment_mw",
                )
                .rename(columns={df.index.name or "ts": "ts"})
            )
            long["region"] = network
            return long[["ts", "region", "fuel", "curtailment_mw"]]
        if metric == "price":
            out = df.reset_index()
            out.columns = ["ts", "price_mwh"]
            out["region"] = network
            return out[["ts", "region", "price_mwh"]]
        if metric == "demand":
            out = df.reset_index()
            out.columns = ["ts", "demand_mw"]
            out["region"] = network
            return out[["ts", "region", "demand_mw"]]
        if metric == "emissions":
            out = df.reset_index()
            out.columns = ["ts", "emissions_intensity_kgco2e_per_mwh"]
            out["region"] = network
            return out[["ts", "region", "emissions_intensity_kgco2e_per_mwh"]]
        if metric == "renewable_proportion":
            out = df.reset_index()
            out.columns = ["ts", "renewable_proportion"]
            out["region"] = network
            return out[["ts", "region", "renewable_proportion"]]
        if metric in ("interconnector_imports", "interconnector_exports"):
            out = df.reset_index()
            out.columns = ["ts", "flow_mw"]
            out["region"] = network
            out["flow_type"] = metric
            return out[["ts", "region", "flow_type", "flow_mw"]]
        if metric == "market_value":
            out = df.reset_index()
            out.columns = ["ts", "market_value"]
            out["region"] = network
            return out[["ts", "region", "market_value"]]
        return pd.DataFrame()

    async def _fetch_with_http(
        self,
        client: httpx.AsyncClient,
        network: str,
        metric: str,
        since: datetime,
        until: datetime,
    ) -> pd.DataFrame:
        offset = NETWORK_UTC_OFFSET_HOURS[network]
        local_since = (
            since.astimezone(timezone.utc) + timedelta(hours=offset)
        ).replace(tzinfo=None)
        local_until = (
            until.astimezone(timezone.utc) + timedelta(hours=offset)
        ).replace(tzinfo=None)
        api_metric = METRIC_API_NAME.get(metric, metric)
        params: dict[str, str] = {
            "metrics": api_metric,
            "interval": "5m",
            "date_start": local_since.isoformat(),
            "date_end": local_until.isoformat(),
        }
        if metric == "power":
            # Only `power` supports secondary_grouping on this API — the
            # `curtailment` metric ignores it (confirmed live: still
            # returns a single "_total" series). Per-fuel curtailment
            # instead uses the dedicated curtailment_solar_utility /
            # curtailment_wind metric names.
            params["secondary_grouping"] = "fueltech"
        base_url = (
            self.MARKET_BASE_URL
            if METRIC_ENDPOINT.get(metric) == "market"
            else self.DATA_BASE_URL
        )
        url = f"{base_url}/{network}"
        log.info("oe.http.request", url=url, metric=metric)

        async def _do_get() -> httpx.Response:
            response = await client.get(
                url, params=params, headers=self.headers, timeout=30.0
            )
            response.raise_for_status()
            return response

        response = await retry_with_backoff(
            _do_get,
            max_retries=self.max_retries,
            backoff_base=self.backoff_base,
            on_retry=lambda attempt, exc, delay: log.warning(
                "oe.http.retry", url=url, attempt=attempt, error=str(exc), sleep=delay
            ),
        )
        body = response.json()
        return self._parse_http_response(body, network, metric)

    def _parse_http_response(
        self,
        body: dict[str, Any],
        network: str,
        metric: str,
    ) -> pd.DataFrame:
        """Parse the v4 HTTP response into a long tidy DataFrame.

        Each `results[]` series carries its grouping as a small static
        dict in `columns` (e.g. `{"fueltech": "wind"}`, or `{}` when
        ungrouped) — NOT a per-row column schema. `data` is a plain
        list of `[timestamp, value]` pairs. The real API exposes no
        data-quality/status field at all on this endpoint, so every
        row normalizes to "unknown"; `merge_network` falls back to
        "realtime" at the document level when the whole column is null.
        """
        rows: list[dict[str, Any]] = []
        for entry in body.get("data", []):
            for series in entry.get("results", []):
                fuel = str(series.get("columns", {}).get("fueltech", "")).lower()
                norm_status = normalize_data_quality(None)
                for ts, value in series.get("data", []):
                    if metric == "power":
                        rows.append(
                            {
                                "ts": ts,
                                "region": network,
                                "fuel": fuel,
                                "mw": value,
                                "data_quality_status": norm_status,
                            }
                        )
                    elif metric == "curtailment_solar_utility":
                        rows.append(
                            {
                                "ts": ts,
                                "region": network,
                                "curtailment_solar_utility_mw": value,
                                "data_quality_status": norm_status,
                            }
                        )
                    elif metric == "curtailment_wind":
                        rows.append(
                            {
                                "ts": ts,
                                "region": network,
                                "curtailment_wind_mw": value,
                                "data_quality_status": norm_status,
                            }
                        )
                    elif metric == "price":
                        rows.append(
                            {
                                "ts": ts,
                                "region": network,
                                "price_mwh": value,
                                "data_quality_status": norm_status,
                            }
                        )
                    elif metric == "demand":
                        rows.append(
                            {
                                "ts": ts,
                                "region": network,
                                "demand_mw": value,
                                "data_quality_status": norm_status,
                            }
                        )
                    elif metric == "emissions":
                        rows.append(
                            {
                                "ts": ts,
                                "region": network,
                                "emissions_intensity_kgco2e_per_mwh": value,
                                "data_quality_status": norm_status,
                            }
                        )
                    elif metric == "renewable_proportion":
                        rows.append(
                            {
                                "ts": ts,
                                "region": network,
                                "renewable_proportion": value,
                                "data_quality_status": norm_status,
                            }
                        )
                    elif metric in ("interconnector_imports", "interconnector_exports"):
                        rows.append(
                            {
                                "ts": ts,
                                "region": network,
                                "flow_type": metric,
                                "flow_mw": value,
                                "data_quality_status": norm_status,
                            }
                        )
                    elif metric == "market_value":
                        rows.append(
                            {
                                "ts": ts,
                                "region": network,
                                "market_value": value,
                                "data_quality_status": norm_status,
                            }
                        )
        return pd.DataFrame(rows)

    # ──────────────────────────────────────────────────────────────
    # Facility registry
    # ──────────────────────────────────────────────────────────────
    async def fetch_facilities_raw(
        self, client: httpx.AsyncClient, network: str
    ) -> pd.DataFrame:
        url = f"{self.FACILITY_BASE_URL}/{network}"
        log.info("oe.facilities.request", url=url)

        async def _do_get() -> httpx.Response:
            response = await client.get(url, headers=self.headers, timeout=30.0)
            response.raise_for_status()
            return response

        response = await retry_with_backoff(
            _do_get,
            max_retries=self.max_retries,
            backoff_base=self.backoff_base,
            on_retry=lambda attempt, exc, delay: log.warning(
                "oe.facilities.retry",
                url=url,
                attempt=attempt,
                error=str(exc),
                sleep=delay,
            ),
        )
        body = response.json()
        return self._parse_facility_response(body, network)

    def _parse_facility_response(
        self, body: dict[str, Any], network: str
    ) -> pd.DataFrame:
        """Normalize the facility registry into our canonical v1.0 schema.

        WEM data quality note: WEM facility records often have null
        `capacity_maximum`. Falls back to `capacity_registered` when
        this happens, and logs it.
        """
        raw_facilities = body.get("data", body.get("facilities", []))
        rows: list[dict[str, Any]] = []
        now = pd.Timestamp.now(tz="UTC")
        for fac in raw_facilities:
            cap_max = fac.get("capacity_maximum")
            cap_reg = fac.get("capacity_registered")
            if cap_max is None and cap_reg is not None:
                log.debug(
                    "oe.facilities.capacity_fallback",
                    facility=fac.get("code") or fac.get("facility_id"),
                    network=network,
                )
            rows.append(
                {
                    "facility_id": fac.get("code")
                    or fac.get("facility_id")
                    or fac.get("id"),
                    "unit_id": fac.get("unit_id") or fac.get("duid"),
                    "name": fac.get("name") or fac.get("facility_name"),
                    "network": network,
                    "region": fac.get("region_id") or fac.get("region"),
                    "fuel_type": fac.get("fuel_type") or fac.get("fueltech"),
                    "fuel_category": fac.get("fuel_category"),
                    "capacity_registered_mw": cap_reg,
                    "capacity_maximum_mw": cap_max if cap_max is not None else cap_reg,
                    "status": fac.get("status"),
                    "commission_date": fac.get("commission_date")
                    or fac.get("operating_start"),
                    "expected_closure_date": fac.get("expected_closure_date")
                    or fac.get("operating_end"),
                    "latitude": fac.get("latitude") or fac.get("lat"),
                    "longitude": fac.get("longitude") or fac.get("lon"),
                    "state": fac.get("state"),
                    "postcode": fac.get("postcode"),
                    "schema_version": SCHEMA_VERSION,
                    "source": "openelectricity",
                    "ingested_at": now,
                }
            )
        return pd.DataFrame(rows)
