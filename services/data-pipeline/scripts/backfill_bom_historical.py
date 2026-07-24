"""Backfill historical BoM weather via Open-Meteo (ERA5) -> MongoDB upsert.

Standalone script (not a pytest test): the live BoM observations.json
endpoint only returns ~24-48h of history, so LSTM training needs this
separate backfill from Open-Meteo's free ERA5 reanalysis archive
instead (same physics as BoM's own sensors — it assimilates BoM
observations — but with no missing values, no quality flags, and
hourly data back to 1940). Emits the same v1.0 schema as the live
fetcher (`source="open_meteo_era5"`, `data_quality_status="final"`),
duplicated into 30-min slots, and writes into the SAME cache/Mongo
collection the live fetcher uses so both coexist for dbt.

This is a one-shot bulk backfill (years of data per run), not a
resumable day-by-day loop like `backfill_aemo.py` — Open-Meteo serves
the whole range in a handful of requests, so there's no meaningful
per-day checkpoint to resume from. Re-running is still safe: upserts
are idempotent on (station_id, ts).

Run directly:

    uv run --active ./scripts/backfill_bom_historical.py                            # 3 years (default), ending ~5 days ago
    uv run --active ./scripts/backfill_bom_historical.py --years 2
    uv run --active ./scripts/backfill_bom_historical.py --start-date 2023-01-01 --end-date 2023-12-31

    # Or via Makefile from the repo root:
    make backfill-bom-historical [YEARS=2] | [START_DATE=2023-01-01 END_DATE=2023-12-31]
"""

import argparse
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pandera.errors

from ecolens.ingestion.sources.bom import HistoricalFetcher
from ecolens.ingestion.sources.bom.schema import (
    ERA5_LAG_DAYS,
    HISTORICAL_TIMEOUT_SECONDS,
)
from ecolens.ingestion.storage.mongo import bulk_upsert, get_db, get_mongo_client
from ecolens.ingestion.validators.bom import validate as validate_docs
from ecolens.shared.observability.logging import get_logger

log = get_logger("backfill_bom_historical")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--years",
        type=int,
        default=None,
        help="years of history to backfill, ending ~5 days ago (ERA5 lag) (default: 3 if no date range given)",
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=None,
        help="first UTC calendar day to backfill, YYYY-MM-DD (inclusive)",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="last UTC calendar day to backfill, YYYY-MM-DD (inclusive, default: today minus the 5-day ERA5 lag)",
    )
    args = parser.parse_args()

    if args.years is not None and (
        args.start_date is not None or args.end_date is not None
    ):
        parser.error("--years cannot be combined with --start-date/--end-date")
    if args.start_date is None and args.end_date is not None:
        parser.error("--end-date requires --start-date")
    return args


async def run(
    *, years: int | None, start_date: date | None, end_date: date | None
) -> None:
    run_id = uuid.uuid4().hex
    fetcher = HistoricalFetcher()
    async with httpx.AsyncClient(timeout=HISTORICAL_TIMEOUT_SECONDS) as client:
        if start_date is not None:
            start = datetime(
                start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc
            )
            end = (
                datetime(
                    end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc
                )
                if end_date is not None
                else datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                - timedelta(days=ERA5_LAG_DAYS)
            )
            docs = await fetcher.fetch_all_stations_for_range(client, start, end)
        else:
            docs = await fetcher.fetch_all_stations(client, years=years or 3)

    log.info("fetch.complete", run_id=run_id, doc_count=len(docs))
    if not docs:
        log.warning("fetch.empty", run_id=run_id)
        return

    try:
        docs = validate_docs(docs)
    except pandera.errors.SchemaError as e:
        log.error("validation.failed", run_id=run_id, error=str(e))
        return
    log.info("validation.passed", run_id=run_id, doc_count=len(docs))

    try:
        fetcher.write_cache(docs)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache_write_failed", run_id=run_id, error=str(exc))

    db = get_db()
    upserted = await bulk_upsert(db, "bom", docs, run_id)
    log.info("mongo.upsert_complete", run_id=run_id, upserted=upserted)

    get_mongo_client().close()


if __name__ == "__main__":
    cli_args = parse_args()
    asyncio.run(
        run(
            years=cli_args.years,
            start_date=cli_args.start_date,
            end_date=cli_args.end_date,
        )
    )
