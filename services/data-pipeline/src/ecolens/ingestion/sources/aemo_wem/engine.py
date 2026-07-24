"""AEMO WEM dispatch fetcher — orchestration layer (no API key, public WEMDE data portal).

Fetches the live and recent WEM (Wholesale Electricity Market, WA's
South West Interconnected System) data from AEMO's public data portal.
Returns documents in the same v1.0 schema as OpenElectricity/AEMO NEM
so downstream dbt models can union all three.

Data source:
    data.wa.aemo.com.au public WEMDE portal (NO authentication required)
    https://data.wa.aemo.com.au/public/market-data/wemde/
    Three independent feeds, confirmed live (2026-07):
        facilityScada                  5-min per-facility generation (MW)
        operationalDemandWithdrawal     5-min system demand (MW)
        referenceTradingPrice           30-min reference trading price ($/MWh)
    Filenames are predictable — `{Prefix}_{YYYY-MM-DD}.json` under
    `current/` for the last day or two, falling back to
    `{Prefix}_{YYYYMMDD}.zip` under `previous/` for older days (unlike
    NEM, no directory-scraping needed). Demand has no current/previous
    split — one flat directory holds full history as plain JSON.
    Granularity: 5-min (generation, demand); 30-min (price)
    Coverage: WEM — a single zone (the SWIS), unlike NEM's 5 regions.

Strategy (client.py -> transformers.py -> here):
    1. Download facilityScada / operationalDemandWithdrawal /
       referenceTradingPrice for the day (client.py).
    2. Map facility codes to fueltechs using the embedded
       FACILITY_FUELTECH_MAP -> aggregate to (ts, fueltech).
    3. Outer-join demand (5-min) and price (30-min, so price is null
       on the timestamps in between — WEM doesn't publish 5-min price).
    4. Apply FUEL_MAP (the same canonical v1.0 columns as OE/NEM).
    5. Compute derived columns (total_generation_mw,
       renewable_proportion). interconnector_*_mw is always 0 — WEM
       is currently islanded.
    6. Apply the same data quality fixes as aemo_nem.py.
    (2-6 are transformers.py; this module concurrently fetches every
    day in range and assembles the final doc list.)

Every document uses region="WEM" — WEM has no NEM-style sub-regions,
so there's no per-region vs network-level split like aemo_nem.py.

Usage:
    fetcher = AEMOWEMFetcher()
    async with httpx.AsyncClient(timeout=60) as client:
        docs = await fetcher.fetch(client, since=..., until=...)
        await bulk_upsert(db, "aemo_wem_dispatch", docs,
                          unique_keys=("ts",))
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from ecolens.ingestion.circuit_breaker import CircuitBreaker
from ecolens.ingestion.sources.openelectricity import NETWORK_UTC_OFFSET_HOURS
from ecolens.shared.observability.logging import get_logger

from .client import AEMOWEMClient
from .schema import FACILITY_FUELTECH_MAP, OUTPUT_COLUMNS
from .transformers import apply_data_quality_fixes, build_day_frame, diagnose

log = get_logger(__name__)

AWST_OFFSET_HOURS = NETWORK_UTC_OFFSET_HOURS["WEM"]  # 8, no DST


class AEMOWEMFetcher:
    """Fetcher for AEMO WEM dispatch data from the public WEMDE data portal.

    No API key, no authentication. Produces single-zone (region="WEM")
    documents in the v1.0 schema (matching openelectricity.py/aemo_nem.py).
    """

    def __init__(
        self,
        *,
        facility_fueltech_map: dict[str, str] | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        """Args:
        facility_fueltech_map: Override the facility-code→fueltech
            mapping. Default uses the embedded FACILITY_FUELTECH_MAP.
        circuit_breaker: optional (default None -- no Redis needed
            unless a caller explicitly wires one in, e.g.
            CircuitBreaker("aemo_wem", get_redis_client())). See ECO-101.
        """
        self.facility_map = (
            facility_fueltech_map
            if facility_fueltech_map is not None
            else FACILITY_FUELTECH_MAP
        )
        self._client = AEMOWEMClient(circuit_breaker=circuit_breaker)

    # ──────────────────────────────────────────────────────────────
    # Public entry points
    # ──────────────────────────────────────────────────────────────
    async def fetch(
        self,
        client: httpx.AsyncClient,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch WEM dispatch data for the date range.

        Args:
            client: shared httpx.AsyncClient (caller manages pool).
            since:  start of range (UTC, tz-aware). Defaults to "1 hour ago".
            until:  end of range (UTC, tz-aware). Defaults to "now".

        Returns:
            A list of dicts ready for bulk_upsert into MongoDB. Each
            dict has all OUTPUT_COLUMNS, with `None` for missing values.
        """
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=1)
        if until is None:
            until = datetime.now(timezone.utc)
        if until < since:
            raise ValueError("`until` is before `since`")

        # Convert UTC → AWST (UTC+8, no DST) for WEMDE file naming
        awst_since = (
            since.astimezone(timezone.utc) + timedelta(hours=AWST_OFFSET_HOURS)
        ).replace(tzinfo=None)
        awst_until = (
            until.astimezone(timezone.utc) + timedelta(hours=AWST_OFFSET_HOURS)
        ).replace(tzinfo=None)
        days = self._daterange(awst_since, awst_until)
        log.info(
            "aemo_wem.fetch.start",
            days=len(days),
            since=since.isoformat(),
            until=until.isoformat(),
        )

        coros = [self._safe_fetch_day(client, day) for day in days]
        results = await asyncio.gather(*coros)

        all_rows: list[pd.DataFrame] = [
            df for df in results if df is not None and not df.empty
        ]
        if not all_rows:
            log.warning("aemo_wem.fetch.no_data")
            return []
        combined = pd.concat(all_rows, ignore_index=True)

        for col in OUTPUT_COLUMNS:
            if col not in combined.columns:
                combined[col] = None
        combined = combined[OUTPUT_COLUMNS]

        docs = combined.to_dict("records")
        docs = apply_data_quality_fixes(docs)
        diagnose(docs)
        log.info("aemo_wem.fetch.complete", rows=len(docs), days=len(days))
        return docs

    async def fetch_for_date(
        self,
        client: httpx.AsyncClient,
        for_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch WEM dispatch data for one whole AWST calendar day.

        Defaults to yesterday (AWST). Files typically land the same
        or following day, so "today" and, right after AWST midnight,
        even "yesterday" can briefly be unpublished — `fetch()` skips
        an unpublished day gracefully, returning `[]` with a logged
        warning rather than raising.
        """
        if for_date is None:
            now_awst = datetime.now(timezone.utc) + timedelta(hours=AWST_OFFSET_HOURS)
            for_date = (now_awst - timedelta(days=1)).date()

        # A single instant at AWST noon on `for_date`, expressed in
        # UTC (AWST = UTC+8, so AWST-noon == 04:00 UTC same date).
        # `fetch()` re-derives the AWST calendar day from since/until
        # via `_daterange`, so since == until == this instant selects
        # exactly that one day.
        target = datetime(
            for_date.year, for_date.month, for_date.day, 4, 0, 0, tzinfo=timezone.utc
        )
        return await self.fetch(client, since=target, until=target)

    # ──────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────
    async def _safe_fetch_day(
        self,
        client: httpx.AsyncClient,
        day: datetime,
    ) -> pd.DataFrame | None:
        try:
            raw = await self._client.fetch_day_data(client, day.date())
        except Exception as exc:  # noqa: BLE001
            log.error(
                "aemo_wem.day.failed", day=day.strftime("%Y-%m-%d"), error=str(exc)
            )
            return None
        if raw is None:
            log.info("aemo_wem.day.not_published", day=day.strftime("%Y-%m-%d"))
            return None
        return build_day_frame(raw, self.facility_map)

    @staticmethod
    def _daterange(start: datetime, end: datetime) -> list[datetime]:
        """Return the days in [start, end] inclusive (AWST-naive)."""
        days: list[datetime] = []
        cur = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end_d = end.replace(hour=0, minute=0, second=0, microsecond=0)
        while cur <= end_d:
            days.append(cur)
            cur += timedelta(days=1)
        return days
