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
    BoM JSON API (no key required)
    http://www.bom.gov.au/fwo/{station_id}/observations.json
    Granularity: 30-min (BoM publishes hourly; floored to 30-min slots)
    Coverage:    6 stations (one per NEM/WEM region)
    Latency:     ~1 hour
    License:     BoM public data, free for commercial use with attribution.

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
        await bulk_upsert(db, "bom", docs, run_id)
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
from .schema import DEFAULT_BOM_STATIONS
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
        bom_stations: dict[str, str] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        """Args:
        bom_stations: Override the region->station mapping. Default
            uses the settings' `bom_stations` (falls back to
            DEFAULT_BOM_STATIONS, 6 stations, one per region).
        cache_dir: Override the cache directory. Default is the
            settings' `bom_cache_dir`.
        """
        settings = get_settings()
        self.stations = (
            bom_stations if bom_stations is not None else settings.bom_stations
        ) or DEFAULT_BOM_STATIONS
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
            A list of dicts ready for bulk_upsert into MongoDB
            (`raw.bom_observations` collection). Each dict has all 22
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
            stations=len(self.stations),
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

        log.warning("bom.fetch.synthetic_stub")
        stub = synthetic_stub(self.stations, since, until)
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
    # Tier 1 — Live BoM JSON API
    # ──────────────────────────────────────────────────────────────
    async def _try_live_api(
        self,
        client: httpx.AsyncClient,
        since: datetime,
        until: datetime,
    ) -> list[dict[str, Any]] | None:
        coros = [
            self._safe_fetch_station(client, region, station_id, since, until)
            for region, station_id in self.stations.items()
        ]
        results = await asyncio.gather(*coros)
        all_rows: list[dict[str, Any]] = []
        for region, rows in zip(self.stations.keys(), results):
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
        station_id: str,
        since: datetime,
        until: datetime,
    ) -> list[dict[str, Any]]:
        try:
            return await self._client.fetch_station(
                client, region, station_id, since, until
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "bom.station.failed", region=region, station=station_id, error=str(exc)
            )
            return []
