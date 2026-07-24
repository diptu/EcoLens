#!/usr/bin/env python3
"""Backfill AEMO NEM/WEM dispatch data over a date range into MongoDB.

Loops day-by-day (inclusive) rather than fetching the whole range in
one shot: each day is fetched and upserted independently, so progress
is persisted incrementally (safe to Ctrl-C and resume from a later
--start) and a single bad day is logged and skipped instead of
aborting the whole backfill. Re-running over an already-backfilled
range is safe — bulk_upsert is idempotent on each source's unique key.

Run from the data-pipeline venv (needs the `ecolens` package):

    cd services/data-pipeline
    uv run --active python ../scripts/backfill_aemo.py \\
        --start 2026-07-01 --end 2026-07-19 --source both

    # Or via Makefile from the repo root:
    make backfill-aemo START=2026-07-01 END=2026-07-19 [SOURCE=nem|wem|both]
"""

import argparse
import asyncio
import uuid
from datetime import date, timedelta

import httpx

from ecolens.ingestion.sources.aemo_nem import AEMONEMFetcher
from ecolens.ingestion.sources.aemo_wem import AEMOWEMFetcher
from ecolens.ingestion.storage.mongo import bulk_upsert, get_db, get_mongo_client
from ecolens.shared.observability.logging import get_logger

log = get_logger("backfill_aemo")

SOURCES = {
    "nem": ("aemo_nem", AEMONEMFetcher),
    "wem": ("aemo_wem", AEMOWEMFetcher),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        required=True,
        help="First day to backfill, YYYY-MM-DD",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        help="Last day to backfill, YYYY-MM-DD (default: same as --start)",
    )
    parser.add_argument(
        "--source",
        choices=["nem", "wem", "both"],
        default="both",
        help="Which source(s) to backfill (default: both)",
    )
    args = parser.parse_args()
    if args.end is None:
        args.end = args.start
    if args.end < args.start:
        parser.error("--end must not be before --start")
    return args


def daterange(start: date, end: date) -> list[date]:
    days = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


async def backfill_one_day(
    client: httpx.AsyncClient, source_key: str, day: date
) -> int:
    """Fetch + upsert one source for one day. Returns docs upserted (0 on failure/no data)."""
    collection_key, fetcher_cls = SOURCES[source_key]
    run_id = uuid.uuid4().hex
    try:
        fetcher = fetcher_cls()
        docs = await fetcher.fetch_for_date(client, day)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "backfill.fetch_failed",
            source=source_key,
            day=day.isoformat(),
            error=str(exc),
        )
        return 0

    if not docs:
        log.warning("backfill.no_data", source=source_key, day=day.isoformat())
        return 0

    db = get_db()
    try:
        upserted = await bulk_upsert(db, collection_key, docs, run_id)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "backfill.upsert_failed",
            source=source_key,
            day=day.isoformat(),
            error=str(exc),
        )
        return 0

    log.info(
        "backfill.day_complete",
        source=source_key,
        day=day.isoformat(),
        doc_count=len(docs),
        upserted=upserted,
    )
    return upserted


async def run(start: date, end: date, source: str) -> None:
    source_keys = list(SOURCES) if source == "both" else [source]
    days = daterange(start, end)
    log.info(
        "backfill.start",
        days=len(days),
        sources=source_keys,
        start=start.isoformat(),
        end=end.isoformat(),
    )

    totals = dict.fromkeys(source_keys, 0)
    async with httpx.AsyncClient(timeout=60) as client:
        for day in days:
            for source_key in source_keys:
                totals[source_key] += await backfill_one_day(client, source_key, day)

    get_mongo_client().close()
    log.info("backfill.complete", days=len(days), totals=totals)


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(args.start, args.end, args.source))
