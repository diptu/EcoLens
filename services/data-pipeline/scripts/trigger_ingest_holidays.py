"""Manually trigger holiday fetch(es) -> MongoDB upsert.

Standalone script (not a pytest test): fetches Australian public
holidays for one or more calendar years (falls back to local cache,
then a synthetic Easter-aware stub, if the live data.gov.au API is
unreachable) and upserts docs into the `aemo_holidays` collection.
Loops year-by-year when a range is given — a bad year is logged and
skipped rather than aborting the rest of the range (same idempotent,
resumable shape as `backfill_aemo.py`). Re-running over an
already-ingested year is safe — bulk_upsert is idempotent on
(region, date).

Run directly:

    uv run --active ./scripts/trigger_ingest_holidays.py                     # current year
    uv run --active ./scripts/trigger_ingest_holidays.py --year 2027
    uv run --active ./scripts/trigger_ingest_holidays.py --start-year 2015 --end-year 2027

    # Or via Makefile from the repo root:
    make ingest-holidays [YEAR=2027] | [START_YEAR=2015 END_YEAR=2027]
"""

import argparse
import asyncio
import uuid
from datetime import date

import httpx
import pandera.errors

from ecolens.ingestion.sources.holidays import HolidayFetcher
from ecolens.ingestion.storage.mongo import bulk_upsert, get_db, get_mongo_client
from ecolens.ingestion.validators.holidays import validate as validate_docs
from ecolens.shared.observability.logging import get_logger

log = get_logger("trigger_ingest_holidays")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="single calendar year to fetch (default: current year if no range given)",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        help="first year of a range to backfill (inclusive)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="last year of a range to backfill, inclusive (default: --start-year)",
    )
    args = parser.parse_args()

    if args.year is not None and (
        args.start_year is not None or args.end_year is not None
    ):
        parser.error("--year cannot be combined with --start-year/--end-year")
    if args.end_year is not None and args.start_year is None:
        parser.error("--end-year requires --start-year")
    if args.start_year is not None:
        if args.end_year is None:
            args.end_year = args.start_year
        if args.end_year < args.start_year:
            parser.error("--end-year must not be before --start-year")
    return args


async def ingest_one_year(fetcher: HolidayFetcher, year: int) -> int:
    """Fetch + validate + cache + upsert one year. Returns docs upserted (0 on failure/no data)."""
    run_id = uuid.uuid4().hex
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            docs = await fetcher.fetch(client, year=year)
    except Exception as exc:  # noqa: BLE001
        log.error("ingest.fetch_failed", run_id=run_id, year=year, error=str(exc))
        return 0

    log.info("fetch.complete", run_id=run_id, year=year, doc_count=len(docs))
    if not docs:
        log.warning("fetch.empty", run_id=run_id, year=year)
        return 0

    try:
        docs = validate_docs(docs)
    except pandera.errors.SchemaError as e:
        log.error("validation.failed", run_id=run_id, year=year, error=str(e))
        return 0
    log.info("validation.passed", run_id=run_id, year=year, doc_count=len(docs))

    try:
        fetcher.write_cache(docs, year=year)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache_write_failed", run_id=run_id, year=year, error=str(exc))

    db = get_db()
    upserted = await bulk_upsert(db, "aemo_holidays", docs, run_id)
    log.info("mongo.upsert_complete", run_id=run_id, year=year, upserted=upserted)
    return upserted


async def run(years: list[int]) -> None:
    fetcher = HolidayFetcher()
    log.info("ingest.start", years=years)

    totals: dict[int, int] = {}
    for year in years:
        totals[year] = await ingest_one_year(fetcher, year)

    get_mongo_client().close()
    log.info("ingest.complete", years=years, totals=totals)


if __name__ == "__main__":
    cli_args = parse_args()
    if cli_args.start_year is not None:
        selected_years = list(range(cli_args.start_year, cli_args.end_year + 1))
    else:
        selected_years = [
            cli_args.year if cli_args.year is not None else date.today().year
        ]
    asyncio.run(run(selected_years))
