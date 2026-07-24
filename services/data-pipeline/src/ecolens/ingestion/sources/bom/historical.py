"""BoM historical weather fetcher — orchestration layer.

Backfill historical BoM weather data via the Open-Meteo Historical
API (ERA5 reanalysis).

The live BoM observations.json endpoint only returns the last 24-48
hours (see `engine.py`). For LSTM training we need 2-3 years of
hourly history per station. This fetcher fills that gap using
Open-Meteo's free archive, which is the same physics (it assimilates
BoM observations) but provides hourly data globally back to 1940.

Why ERA5 / Open-Meteo?
======================
ERA5 is ECMWF's fifth-generation reanalysis. It blends historical
observations (including BoM) with a physical model to produce a
globally consistent hourly dataset. For ML training it's better than
raw BoM observations because:
  - No missing values (sensors go down, reanalysis doesn't)
  - No quality flags to deal with
  - Same hourly grain as our 30-min energy data (duplicated into
    both half-hour slots by `historical_transformers.parse_open_meteo_response`)
  - Same v1.0 schema as the live fetcher, so downstream code (dbt, ML
    training) doesn't need to know which source provided a row.

Cost: $0. License: CC-BY 4.0 (attribution required).

Strategy (historical_client.py -> historical_transformers.py -> here):
    1. Chunk the requested date range into <=365-day pieces (Open-Meteo's
       per-request limit).
    2. Fetch every (region, chunk) concurrently across regions
       (historical_client.py); a chunk request failing aborts that
       region's range (unlike the live fetcher, partial historical
       data for one region is not useful for training).
    3. Cache to the SAME directory the live fetcher uses
       (`cache.write_cache`, deduped on (region, ts, station_id)), so
       live and backfilled rows coexist in one place for dbt to read.

Usage:
    fetcher = HistoricalFetcher()
    async with httpx.AsyncClient(timeout=60) as client:
        docs = await fetcher.fetch_all_stations(client, years=3)
        # ~52,500 docs backfilled in 1-2 minutes
        await bulk_upsert(db, "bom", docs, run_id)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from ecolens.config import get_settings
from ecolens.shared.observability.logging import get_logger

from . import cache as cache_module
from .historical_client import OpenMeteoClient
from .schema import ERA5_LAG_DAYS, OPEN_METEO_MAX_CHUNK_DAYS

log = get_logger(__name__)


class HistoricalFetcher:
    """Backfill historical BoM weather via Open-Meteo (ERA5 reanalysis)."""

    def __init__(
        self,
        *,
        bom_stations: dict[str, str] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        settings = get_settings()
        self.stations = (
            bom_stations if bom_stations is not None else settings.bom_stations
        )
        self.cache_dir = cache_dir if cache_dir is not None else settings.bom_cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = OpenMeteoClient()

    # ──────────────────────────────────────────────────────────────
    # Public entry points
    # ──────────────────────────────────────────────────────────────
    async def fetch_range(
        self,
        client: httpx.AsyncClient,
        region: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]] | None:
        """Fetch one date range for one region, chunked at <=365 days.

        Returns None if any chunk ultimately failed (partial
        historical data for one region isn't useful for training, so
        we don't return a partial result).
        """
        all_docs: list[dict[str, Any]] = []
        for chunk_start, chunk_end in self._chunk_range(start, end):
            docs = await self._client.fetch_chunk(
                client, region, chunk_start, chunk_end, self.stations
            )
            if docs is None:
                return None
            all_docs.extend(docs)
        return all_docs

    async def fetch_all_stations(
        self,
        client: httpx.AsyncClient,
        years: int = 3,
    ) -> list[dict[str, Any]]:
        """Fetch `years` of history for all configured stations, ending ~ERA5_LAG_DAYS ago."""
        end = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=ERA5_LAG_DAYS)
        start = end - timedelta(days=365 * years)
        return await self.fetch_all_stations_for_range(client, start, end)

    async def fetch_all_stations_for_range(
        self,
        client: httpx.AsyncClient,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch an explicit [start, end] date range for all configured stations.

        Use this instead of `fetch_all_stations` when backfilling a
        specific window (e.g. to retry a failed region, or fill a gap)
        rather than "N years back from now".
        """
        if end < start:
            raise ValueError("`end` is before `start`")
        log.info(
            "bom_historical.backfill.start",
            start=start.date().isoformat(),
            end=end.date().isoformat(),
            regions=len(self.stations),
        )
        coros = [
            self.fetch_range(client, region, start, end) for region in self.stations
        ]
        results = await asyncio.gather(*coros)
        all_docs: list[dict[str, Any]] = []
        for region, docs in zip(self.stations.keys(), results):
            if docs:
                all_docs.extend(docs)
                log.info("bom_historical.region.done", region=region, rows=len(docs))
            else:
                log.warning("bom_historical.region.failed", region=region)
        log.info("bom_historical.backfill.complete", rows=len(all_docs))
        return all_docs

    def write_cache(self, docs: list[dict[str, Any]]) -> list[Path]:
        """Persist docs to the same local cache the live fetcher reads/writes."""
        return cache_module.write_cache(self.cache_dir, docs)

    # ──────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def _chunk_range(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        """Split [start, end] into <=365-day inclusive chunks."""
        chunks: list[tuple[datetime, datetime]] = []
        cur = start
        while cur <= end:
            chunk_end = min(cur + timedelta(days=OPEN_METEO_MAX_CHUNK_DAYS), end)
            chunks.append((cur, chunk_end))
            cur = chunk_end + timedelta(days=1)
        return chunks


__all__ = ["HistoricalFetcher"]
