"""Manually trigger BoM fetch(es) -> MongoDB upsert.

Standalone script (not a pytest test): fetches observations for the 6
default NEM/WEM stations (falls back to local cache, then a synthetic
stub, if the live API is unreachable) and upserts docs into the
`bom_observations` collection. Defaults to the last 1 hour
(near-real-time); also supports a single past UTC day or a day-by-day
range for backfill, mirroring `backfill_aemo.py` / the holidays
trigger's year range — a bad day is logged and skipped rather than
aborting the rest of the range, and re-running an already-ingested day
is safe (bulk_upsert is idempotent on (station_id, ts)).

Caveat: BoM's live JSON API only exposes ~72 hours of recent
observations. Requesting a day older than that will not pull real
historical weather — it falls through to the local CSV cache (if that
day was fetched previously) or, failing that, the deterministic
synthetic stub (NOT real weather, dev/CI use only). This script does
not reach back further in time than what's already cached.

Run directly:

    uv run --active ./scripts/trigger_ingest_bom.py                                          # last 1 hour
    uv run --active ./scripts/trigger_ingest_bom.py --date 2026-07-01                         # one full UTC day
    uv run --active ./scripts/trigger_ingest_bom.py --start-date 2026-06-01 --end-date 2026-07-01  # range, day by day

    # Or via Makefile from the repo root:
    make ingest-bom [DATE=2026-07-01] | [START_DATE=2026-06-01 END_DATE=2026-07-01]
"""

import argparse
import asyncio
import uuid
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pandera.errors

from ecolens.config import get_settings
from ecolens.ingestion.sources.bom import BomFetcher
from ecolens.ingestion.storage.mongo import bulk_upsert, get_db, get_mongo_client
from ecolens.ingestion.validators.bom import validate as validate_docs
from ecolens.shared.observability.logging import get_logger

log = get_logger("trigger_ingest_bom")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="single UTC calendar day to fetch, YYYY-MM-DD (default: last 1 hour)",
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=None,
        help="first UTC calendar day of a range to backfill (inclusive)",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="last UTC calendar day of a range to backfill, inclusive (default: --start-date)",
    )
    args = parser.parse_args()

    if args.date is not None and (
        args.start_date is not None or args.end_date is not None
    ):
        parser.error("--date cannot be combined with --start-date/--end-date")
    if args.end_date is not None and args.start_date is None:
        parser.error("--end-date requires --start-date")
    if args.start_date is not None:
        if args.end_date is None:
            args.end_date = args.start_date
        if args.end_date < args.start_date:
            parser.error("--end-date must not be before --start-date")
    return args


def day_bounds(day: date) -> tuple[datetime, datetime]:
    since = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return since, since + timedelta(days=1)


def daterange(start: date, end: date) -> list[date]:
    days = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


async def ingest_window(
    fetcher: BomFetcher,
    timeout: int,
    since: datetime | None,
    until: datetime | None,
    *,
    label: str,
) -> int:
    """Fetch + validate + cache + upsert one time window. Returns docs upserted (0 on failure/no data)."""
    run_id = uuid.uuid4().hex
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            docs = await fetcher.fetch(client, since=since, until=until)
    except Exception as exc:  # noqa: BLE001
        log.error("ingest.fetch_failed", run_id=run_id, window=label, error=str(exc))
        return 0

    log.info("fetch.complete", run_id=run_id, window=label, doc_count=len(docs))
    if not docs:
        log.warning("fetch.empty", run_id=run_id, window=label)
        return 0

    try:
        docs = validate_docs(docs)
    except pandera.errors.SchemaError as e:
        log.error("validation.failed", run_id=run_id, window=label, error=str(e))
        return 0
    log.info("validation.passed", run_id=run_id, window=label, doc_count=len(docs))

    try:
        fetcher.write_cache(docs)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache_write_failed", run_id=run_id, window=label, error=str(exc))

    db = get_db()
    upserted = await bulk_upsert(db, "bom", docs, run_id)
    log.info("mongo.upsert_complete", run_id=run_id, window=label, upserted=upserted)
    return upserted


async def run(windows: list[tuple[datetime | None, datetime | None, str]]) -> None:
    settings = get_settings()
    fetcher = BomFetcher()
    log.info("ingest.start", windows=[label for *_rest, label in windows])

    totals: dict[str, int] = {}
    for since, until, label in windows:
        totals[label] = await ingest_window(
            fetcher, settings.bom_request_timeout_seconds, since, until, label=label
        )

    get_mongo_client().close()
    log.info("ingest.complete", totals=totals)


if __name__ == "__main__":
    cli_args = parse_args()
    if cli_args.start_date is not None:
        windows = [
            (*day_bounds(d), d.isoformat())
            for d in daterange(cli_args.start_date, cli_args.end_date)
        ]
    elif cli_args.date is not None:
        since, until = day_bounds(cli_args.date)
        windows = [(since, until, cli_args.date.isoformat())]
    else:
        windows = [(None, None, "last-1-hour")]
    asyncio.run(run(windows))
