"""AEMO NEM dispatch fetcher — orchestration layer (no API key, public NEMWeb archive).

Fetches the live and recent NEM dispatch data from AEMO's public
NEMWeb archive. Returns documents in the same v1.0 schema as
OpenElectricity so downstream dbt models can union them.

Data source:
    NEMWeb public archive (NO authentication required)
    https://www.nemweb.com.au/Reports/Current/Daily_Reports/
    Files: PUBLIC_DAILY_{YYYYMMDD}0000_{publish-timestamp}.zip — the
    publish timestamp is not predictable (files land ~4am the next
    day), so the URL is resolved by scraping the directory listing,
    not constructed from a fixed pattern.
    Granularity: 5-min intervals
    Coverage: NEM (NSW1, QLD1, VIC1, SA1, TAS1)

Inside the ZIP (confirmed against a live file — NOT the classic
per-table-CSV NEMWeb format some docs describe):
    One combined AEMO MMS multi-table CSV. `I,<table>,<subtable>,...`
    rows define a table's header; `D,<table>,<subtable>,...` rows
    that follow are its data, until the next `I,` row. Tables used:
        DUNIT     per-unit dispatch (DUID, TOTALCLEARED, INTERVENTION)
        DREGION   per-region summary (REGIONID, TOTALDEMAND, RRP,
                   NETINTERCHANGE — this alone covers demand, price,
                   and interconnector net flow; there's no separate
                   DISPATCHINTERCONNECTORRES table in this report).
    Both tables carry duplicate rows for INTERVENTION pricing runs —
    filtered to INTERVENTION == "0" (the physical dispatch run).

Strategy (client.py -> transformers.py -> here):
    1. Resolve the day's ZIP URL from the NEMWeb directory listing,
       download and decode it (client.py).
    2. Parse DUNIT -> map DUIDs to fueltechs using the embedded
       DUID_FUELTECH_MAP -> aggregate to network-level (ts, fueltech).
    3. Parse DREGION -> regional demand, price, and net interconnector
       flow.
    4. Apply FUEL_MAP (the same canonical v1.0 columns as OE).
    5. Compute derived columns (total_generation_mw,
       renewable_proportion, emissions_intensity).
    6. Apply the same data quality fixes as openelectricity.py.
    (2-6 are transformers.py; this module concurrently fetches every
    day in range and assembles the final doc list.)

The fetcher emits PER-REGION documents (region = "NSW1" / "QLD1" /
"VIC1" / "SA1" / "TAS1") for demand/price/flow, plus one network-level
("NEM") document per ts for the fueltech mix — unlike openelectricity.py
which emits network-level only. This is more useful for the LSTM
(regional demand/price patterns matter). Set aggregate_to_network=True
to roll everything up to a single "NEM" row per ts.

WEM is NOT handled here — see aemo_wem.py.

Usage:
    fetcher = AEMONEMFetcher()
    async with httpx.AsyncClient(timeout=60) as client:
        docs = await fetcher.fetch(client, since=..., until=...)
        await bulk_upsert(db, "aemo_nem_dispatch", docs,
                          unique_keys=("region", "ts"))
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from ecolens.shared.observability.logging import get_logger

from .client import AEMONEMClient
from .schema import DUID_FUELTECH_MAP, OUTPUT_COLUMNS
from .transformers import (
    aggregate_to_network,
    apply_data_quality_fixes,
    build_day_frame,
    diagnose,
)

log = get_logger(__name__)


class AEMONEMFetcher:
    """Fetcher for AEMO NEM dispatch data from NEMWeb public archive.

    No API key, no authentication. NEMWeb files are public CSVs
    inside daily ZIPs. This fetcher produces per-region documents
    in the v1.0 schema (matching openelectricity.py).
    """

    def __init__(
        self,
        *,
        aggregate_to_network: bool = False,
        duid_fueltech_map: dict[str, str] | None = None,
    ) -> None:
        """Args:
        aggregate_to_network: If True, emit one doc per (network="NEM",
            ts) with regions aggregated. Default False (per-region docs).
        duid_fueltech_map: Override the DUID→fueltech mapping. Default
            uses the embedded DUID_FUELTECH_MAP.
        """
        self.aggregate_to_network = aggregate_to_network
        self.duid_map = (
            duid_fueltech_map if duid_fueltech_map is not None else DUID_FUELTECH_MAP
        )
        self._client = AEMONEMClient()

    # ──────────────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────────────
    async def fetch(
        self,
        client: httpx.AsyncClient,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch NEM dispatch data for the date range.

        Args:
            client: shared httpx.AsyncClient (caller manages pool).
            since:  start of range (UTC, tz-aware). Defaults to "1 hour ago"
                    — NEMWeb publishes files daily, so the most recent day
                    ZIP covers everything from 00:00 to ~current time.
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

        # Convert UTC → AEST (UTC+10, no DST) for NEMWeb file naming
        aest_since = (since.astimezone(timezone.utc) + timedelta(hours=10)).replace(
            tzinfo=None
        )
        aest_until = (until.astimezone(timezone.utc) + timedelta(hours=10)).replace(
            tzinfo=None
        )
        days = self._daterange(aest_since, aest_until)
        log.info(
            "aemo_nem.fetch.start",
            days=len(days),
            since=since.isoformat(),
            until=until.isoformat(),
        )

        # Fetch every day's ZIP in parallel
        coros = [self._safe_fetch_day(client, day) for day in days]
        results = await asyncio.gather(*coros)

        # Combine the per-day DataFrames
        all_rows: list[pd.DataFrame] = [
            df for df in results if df is not None and not df.empty
        ]
        if not all_rows:
            log.warning("aemo_nem.fetch.no_data")
            return []
        combined = pd.concat(all_rows, ignore_index=True)

        # Aggregate to network level if requested
        if self.aggregate_to_network:
            combined = aggregate_to_network(combined)

        # Guarantee the full v1.0 column set, same contract as
        # openelectricity.py, so downstream code never has to
        # branch on which source a doc came from.
        for col in OUTPUT_COLUMNS:
            if col not in combined.columns:
                combined[col] = None
        combined = combined[OUTPUT_COLUMNS]

        # Convert to dicts and apply the data quality fixes
        docs = combined.to_dict("records")
        docs = apply_data_quality_fixes(docs)
        diagnose(docs)
        log.info("aemo_nem.fetch.complete", rows=len(docs), days=len(days))
        return docs

    async def fetch_for_date(
        self,
        client: httpx.AsyncClient,
        for_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch NEM dispatch data for one whole AEST calendar day.

        Defaults to yesterday (AEST) — NEMWeb publishes each day's
        file ~4am the *following* day, so "today" almost never has
        data yet (AEMONEMClient.fetch_day_tables returns None for an
        unpublished day, and `fetch()` just skips it, returning `[]`
        with a logged warning rather than raising). Note this means
        even the default "yesterday" can be transiently unpublished
        for the first few hours after AEST midnight — pass an explicit
        `for_date` two days back if you hit that window.
        """
        if for_date is None:
            now_aest = datetime.now(timezone.utc) + timedelta(hours=10)
            for_date = (now_aest - timedelta(days=1)).date()

        # A single instant at AEST noon on `for_date`, expressed in
        # UTC (AEST = UTC+10, so AEST-noon == 02:00 UTC same date).
        # `fetch()` re-derives the AEST calendar day from since/until
        # via `_daterange`, so since == until == this instant selects
        # exactly that one day.
        target = datetime(
            for_date.year, for_date.month, for_date.day, 2, 0, 0, tzinfo=timezone.utc
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
            tables = await self._client.fetch_day_tables(client, day)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                log.info("aemo_nem.day.no_data", day=day.strftime("%Y-%m-%d"))
                return None
            log.error("aemo_nem.day.failed", day=day.strftime("%Y-%m-%d"), error=str(e))
            return None
        except Exception as exc:  # noqa: BLE001
            log.error(
                "aemo_nem.day.failed", day=day.strftime("%Y-%m-%d"), error=str(exc)
            )
            return None
        if tables is None:
            log.info("aemo_nem.day.not_published", day=day.strftime("%Y-%m-%d"))
            return None
        return build_day_frame(tables, self.duid_map)

    @staticmethod
    def _daterange(start: datetime, end: datetime) -> list[datetime]:
        """Return the days in [start, end] inclusive (AEST-naive)."""
        days: list[datetime] = []
        cur = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end_d = end.replace(hour=0, minute=0, second=0, microsecond=0)
        while cur <= end_d:
            days.append(cur)
            cur += timedelta(days=1)
        return days
