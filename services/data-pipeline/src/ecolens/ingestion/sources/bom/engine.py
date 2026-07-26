"""BoM observation fetcher — orchestration layer, schema v1.0.

Bureau of Meteorology (BoM) public observations for the 6 default
NEM/WEM stations. One station per region. Hourly observations floored
to 30-min slots so they join cleanly with the energy data.

This is a *side-dataset* fetcher (unlike aemo_nem/aemo_wem/
openelectricity, which emit the v1.0 energy schema). It emits a
dedicated weather schema (`schema.OBSERVATION_OUTPUT_COLUMNS`, 22
columns) that the dbt weather model joins onto the energy fact table
on (region, ts_local). The downstream LSTM uses temperature, humidity
and wind as exogenous features (e.g. heatwave days -> demand spikes).

Data source:
    BoM v1 observations API (no key required)
    https://api.weather.bom.gov.au/v1/locations/{geohash}/observations
    Granularity: 30-min (BoM publishes ~hourly; floored to 30-min slots)
    Coverage:    6 stations (one per NEM/WEM region), current
                 observation only -- no history, no date-range params
    Latency:     ~1 hour
    License:     BoM data free for non-commercial use (see
                 bom_obserbation.md); commercial use requires
                 registration at bom.gov.au/weather-data.

    Stations are addressed by geohash, not the legacy numeric station
    ID (schema.DEFAULT_BOM_GEOHASHES) -- the v1 API resolves each
    geohash to its nearest station and returns that station's own
    canonical ID/name in the response, which the live tier trusts
    over any locally hardcoded ID (see transformers.normalize_observation).

Strategy (client.py -> transformers.py -> here):
    `fetch()` tries three tiers in order, same shape as the energy
    fetchers' resilience story but with an extra local-cache tier
    since BoM has no historical replay API of its own:
      1. Live API — every station fetched concurrently (client.py),
         one station's failure doesn't kill the others.
      2. Local CSV cache (cache.py) — whatever a previous successful
         live fetch wrote to disk.
      3. Synthetic stub (transformers.py) — deterministic, seeded PRNG;
         dev/CI only, never used against production data.
    Every tier's output passes through the same
    `transformers.apply_data_quality_fixes` + `transformers.diagnose`.

Usage:
    fetcher = BomFetcher()
    async with httpx.AsyncClient(timeout=30) as client:
        docs = await fetcher.fetch(client, since=..., until=...)
        duckdb_store.write_historical("bom", docs)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from ecolens.config import get_settings
from ecolens.shared.observability.logging import get_logger

from . import cache as cache_module
from .client import BomClient
from .schema import DEFAULT_BOM_GEOHASHES, DEFAULT_BOM_STATIONS
from .transformers import apply_data_quality_fixes, diagnose, synthetic_stub

log = get_logger(__name__)


class BomFetcher:
    """Fetcher for Bureau of Meteorology observations.

    3-tier strategy (live -> cache -> synthetic). Emits the weather
    v1.0 schema (`schema.OBSERVATION_OUTPUT_COLUMNS`).
    """

    def __init__(
        self,
        *,
        bom_geohashes: dict[str, str] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        """Args:
        bom_geohashes: Override the region->geohash mapping used for
            the live v1 API. Default uses the settings' `bom_geohashes`
            (falls back to DEFAULT_BOM_GEOHASHES, 6 stations, one per
            region). Not the same map as the historical fetcher's
            `bom_stations` (canonical station IDs) -- see schema.py.
        cache_dir: Override the cache directory. Default is the
            settings' `bom_cache_dir`.
        """
        settings = get_settings()
        self.geohashes = (
            bom_geohashes if bom_geohashes is not None else settings.bom_geohashes
        ) or DEFAULT_BOM_GEOHASHES
        self.cache_dir = cache_dir if cache_dir is not None else settings.bom_cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = BomClient()

    # ──────────────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────────────
    async def fetch(
        self,
        client: httpx.AsyncClient,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch BoM observations for all configured stations.

        Args:
            client: shared httpx.AsyncClient (caller manages pool).
            since:  start of range (UTC, tz-aware). Defaults to
                    "1 hour ago" — BoM publishes hourly, so the
                    current + previous hour is what we want.
            until:  end of range (UTC, tz-aware). Defaults to "now".

        Returns:
            A list of dicts ready for duckdb_store.write_historical
            (`bom_observations` table). Each dict has all 22
            `schema.OBSERVATION_OUTPUT_COLUMNS`, with `None` for
            missing values. One doc per (region, ts).
        """
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=1)
        if until is None:
            until = datetime.now(timezone.utc)
        if until < since:
            raise ValueError("`until` is before `since`")

        log.info(
            "bom.fetch.start",
            stations=len(self.geohashes),
            since=since.isoformat(),
            until=until.isoformat(),
        )

        live_docs = await self._try_live_api(client, since, until)
        if live_docs:
            log.info("bom.fetch.live_ok", rows=len(live_docs))
            docs = apply_data_quality_fixes(live_docs)
            diagnose(docs)
            return docs

        cached = cache_module.read_cache(self.cache_dir, since, until)
        if cached:
            log.info("bom.fetch.cache_hit", rows=len(cached))
            docs = apply_data_quality_fixes(cached)
            diagnose(docs)
            return docs

        # Synthetic stub keys off the canonical station ID map, not
        # self.geohashes -- it's a fixed dev/CI stub over the 6
        # regions regardless of which geohash the live tier was
        # configured with, and synthetic_stub()'s deterministic
        # per-station seeding expects a real numeric BoM ID.
        log.warning("bom.fetch.synthetic_stub")
        stub = synthetic_stub(DEFAULT_BOM_STATIONS, since, until)
        docs = apply_data_quality_fixes(stub)
        diagnose(docs)
        return docs

    def write_cache(
        self,
        docs: list[dict[str, Any]],
        *,
        region: str | None = None,
    ) -> list[Path]:
        """Persist a batch of docs to the local cache (see cache.py)."""
        return cache_module.write_cache(self.cache_dir, docs, region=region)

    # ──────────────────────────────────────────────────────────────
    # Tier 1 — Live BoM v1 API
    # ──────────────────────────────────────────────────────────────
    async def _try_live_api(
        self,
        client: httpx.AsyncClient,
        since: datetime,
        until: datetime,
    ) -> list[dict[str, Any]] | None:
        coros = [
            self._safe_fetch_station(client, region, geohash, since, until)
            for region, geohash in self.geohashes.items()
        ]
        results = await asyncio.gather(*coros)
        all_rows: list[dict[str, Any]] = []
        for region, rows in zip(self.geohashes.keys(), results):
            if rows:
                all_rows.extend(rows)
            else:
                log.warning("bom.station.empty", region=region)
        if not all_rows:
            return None
        run_id = str(uuid.uuid4())
        for r in all_rows:
            r["ingest_run_id"] = run_id
        return all_rows

    async def _safe_fetch_station(
        self,
        client: httpx.AsyncClient,
        region: str,
        geohash: str,
        since: datetime,
        until: datetime,
    ) -> list[dict[str, Any]]:
        try:
            return await self._client.fetch_station(
                client, region, geohash, since, until
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "bom.station.failed", region=region, geohash=geohash, error=str(exc)
            )
            return []
