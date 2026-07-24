"""Australian public holiday fetcher — orchestration layer, schema v1.0.

Australian public holidays per NEM/WEM region. This is NOT a
time-series fetcher — holidays are date markers that the dbt
warehouse joins with the energy fact table to flag demand-impacting
days (Christmas, NYE, AFL Grand Final, etc.). The LSTM uses these as
binary features: `is_holiday = 1` shifts the demand profile
significantly (e.g. -25% on Christmas Day, -40% on AFL Grand Final
Friday in VIC).

Data source:
    Primary:  data.gov.au — "Australian Public Holidays" combined
              dataset (data.gov.au/data/dataset/australian-public-holidays-combined)
    Fallback: local CSV cache
    Local:    <cache_dir>/holidays_<region>_<YYYY>.csv

Strategy (client.py -> transformers.py -> here):
    Same 3-tier shape as `bom`, but this is a once-a-year pull, not a
    continuous time-series ingest:
      1. Live API — data.gov.au combined dataset (client.py).
      2. Local CSV cache (cache.py) — whatever a previous successful
         live fetch wrote to disk.
      3. Synthetic stub (transformers.py) — deterministic, Easter-aware
         (transformers.easter_date), built from the static per-state
         holiday templates in schema.py; dev/CI only.
    Every tier's output passes through the same
    `transformers.apply_data_quality_fixes` + `transformers.diagnose`,
    then gets `days_until` attached relative to "today".

Usage:
    fetcher = HolidayFetcher()
    docs = fetcher.fetch_for_year(2026)
    # or, to try the live tier first:
    async with httpx.AsyncClient(timeout=30) as client:
        docs = await fetcher.fetch(client, year=2026)
        await bulk_upsert(db, "aemo_holidays", docs, run_id)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import httpx

from ecolens.config import get_settings
from ecolens.ingestion.circuit_breaker import CircuitBreaker
from ecolens.shared.observability.logging import get_logger

from . import cache as cache_module
from .client import HolidayClient
from .schema import NEM_REGIONS
from .transformers import (
    apply_data_quality_fixes,
    attach_days_until,
    diagnose,
    synthetic_stub,
)

log = get_logger(__name__)


class HolidayFetcher:
    """Fetcher for Australian public holidays per NEM/WEM region.

    3-tier strategy (live -> cache -> synthetic). Unlike the other
    fetchers, this is a once-a-year pull, not a continuous
    time-series ingest.
    """

    def __init__(
        self,
        *,
        regions: tuple[str, ...] | None = None,
        cache_dir: Path | None = None,
        today: date | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        settings = get_settings()
        self.regions = regions if regions is not None else NEM_REGIONS
        self.cache_dir = (
            cache_dir if cache_dir is not None else settings.holidays_cache_dir
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # `today` is injectable for deterministic testing
        self._today = today or date.today()
        # `circuit_breaker` is optional (default None -- no Redis needed
        # unless a caller explicitly wires one in, e.g.
        # CircuitBreaker("holidays", get_redis_client())). See ECO-101.
        self._client = HolidayClient(circuit_breaker=circuit_breaker)

    # ──────────────────────────────────────────────────────────────
    # Public entry points
    # ──────────────────────────────────────────────────────────────
    async def fetch(
        self,
        client: httpx.AsyncClient | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all holidays for the given year.

        Args:
            client: shared httpx.AsyncClient (caller manages pool).
                    Optional — only needed for the live tier.
            year: which year to fetch. Defaults to current year.

        Returns:
            A list of dicts, one per (region, date) holiday, ready
            for bulk_upsert into MongoDB (`aemo_holidays` collection).
            Each dict has all 13 `schema.HOLIDAY_OUTPUT_COLUMNS`.
        """
        if year is None:
            year = self._today.year

        log.info("holidays.fetch.start", year=year, regions=len(self.regions))

        if client is not None:
            live_docs = await self._client.fetch_year(client, year)
            if live_docs:
                log.info("holidays.fetch.live_ok", rows=len(live_docs))
                return self._finalize(live_docs, year)

        cached = cache_module.read_cache(self.cache_dir, self.regions, year)
        if cached:
            log.info("holidays.fetch.cache_hit", rows=len(cached))
            return self._finalize(cached, year)

        log.warning("holidays.fetch.synthetic_stub")
        stub = synthetic_stub(self.regions, year)
        return self._finalize(stub, year)

    def fetch_for_year(self, year: int | None = None) -> list[dict[str, Any]]:
        """Synchronous convenience wrapper (no network — cache or synthetic only)."""
        if year is None:
            year = self._today.year
        cached = cache_module.read_cache(self.cache_dir, self.regions, year)
        if cached:
            return self._finalize(cached, year)
        stub = synthetic_stub(self.regions, year)
        return self._finalize(stub, year)

    def write_cache(self, docs: list[dict[str, Any]], *, year: int) -> list[Path]:
        """Persist a batch of docs to the local cache (see cache.py)."""
        return cache_module.write_cache(self.cache_dir, docs, year=year)

    # ──────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────
    def _finalize(self, docs: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
        cleaned = apply_data_quality_fixes(docs, year, self.regions)
        diagnose(cleaned)
        attach_days_until(cleaned, self._today)
        return cleaned
