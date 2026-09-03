"""Manually trigger holiday fetch(es) -> DuckDB upsert.

Standalone script (not a pytest test): fetches Australian public
holidays for one or more calendar years (falls back to local cache,
then a synthetic Easter-aware stub, if the live data.gov.au API is
unreachable) and upserts docs into the `aemo_holidays` table.
Loops year-by-year when a range is given — a bad year is logged and
skipped rather than aborting the rest of the range (same idempotent,
resumable shape as `backfill_aemo.py`). Re-running over an
already-ingested year is safe — write_historical is idempotent on
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
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx
import pandera.errors

from ecolens.ingestion.core.data_source_overrides import is_source_enabled
from ecolens.ingestion.core.run_history import record_run
from ecolens.ingestion.service.holidays import HolidayFetcher
from ecolens.ingestion.db import duckdb_store
from ecolens.ingestion.schema.validators.holidays import validate as validate_docs
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


@dataclass(frozen=True)
class _YearResult:
    written: int
    fetched: int
    anomalies_flagged: int
    error: str | None


async def ingest_one_year(fetcher: HolidayFetcher, year: int) -> _YearResult:
    """Fetch + validate + cache + upsert one year."""
    run_id = uuid.uuid4().hex
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            docs = await fetcher.fetch(client, year=year)
    except Exception as exc:  # noqa: BLE001
        log.error("ingest.fetch_failed", run_id=run_id, year=year, error=str(exc))
        return _YearResult(0, 0, 0, str(exc))

    log.info("fetch.complete", run_id=run_id, year=year, doc_count=len(docs))
    if not docs:
        log.warning("fetch.empty", run_id=run_id, year=year)
        return _YearResult(0, 0, 0, None)

    try:
        docs = validate_docs(docs)
    except pandera.errors.SchemaError as e:
        log.error("validation.failed", run_id=run_id, year=year, error=str(e))
        return _YearResult(0, len(docs), 0, str(e))
    log.info("validation.passed", run_id=run_id, year=year, doc_count=len(docs))

    try:
        fetcher.write_cache(docs, year=year)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache_write_failed", run_id=run_id, year=year, error=str(exc))

    written = duckdb_store.write_historical("aemo_holidays", docs, run_id=run_id)
    log.info("duckdb.write_complete", run_id=run_id, year=year, written=written)
    anomalies_flagged = sum(1 for d in docs if d.get("anomaly_score", 0.0) > 0.0)
    return _YearResult(written, len(docs), anomalies_flagged, None)


async def run(years: list[int]) -> None:
    if not is_source_enabled("aemo_holidays"):
        log.info("source.disabled", source="aemo_holidays", hint="skipping this run")
        return

    started_at = datetime.now(timezone.utc)
    run_id = uuid.uuid4().hex
    fetcher = HolidayFetcher()
    log.info("ingest.start", years=years)

    totals: dict[int, int] = {}
    results: list[_YearResult] = []
    for year in years:
        result = await ingest_one_year(fetcher, year)
        totals[year] = result.written
        results.append(result)

    log.info("ingest.complete", years=years, totals=totals)

    fetched = sum(r.fetched for r in results)
    written = sum(r.written for r in results)
    anomalies_flagged = sum(r.anomalies_flagged for r in results)
    errors = [r.error for r in results if r.error is not None]
    if errors and not written:
        status, error = "failed", "; ".join(errors)
    elif not fetched:
        status, error = "empty", None
    else:
        status, error = "success", ("; ".join(errors) if errors else None)
    record_run(
        "aemo_holidays",
        status=status,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        records_fetched=fetched,
        records_inserted=written,
        anomalies_flagged=anomalies_flagged,
        error=error,
        run_id=run_id,
    )


if __name__ == "__main__":
    cli_args = parse_args()
    if cli_args.start_year is not None:
        selected_years = list(range(cli_args.start_year, cli_args.end_year + 1))
    else:
        selected_years = [
            cli_args.year if cli_args.year is not None else date.today().year
        ]
    asyncio.run(run(selected_years))
