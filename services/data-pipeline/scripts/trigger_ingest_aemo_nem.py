"""Manually trigger one AEMO NEM fetch -> DuckDB upsert.

Standalone script (not a pytest test): downloads NEMWeb dispatch data
(public, no API key) and upserts per-region docs into the
`aemo_nem_dispatch` table. Run directly:

    uv run --active ./scripts/trigger_ingest_aemo_nem.py                # yesterday (AEST)
    uv run --active ./scripts/trigger_ingest_aemo_nem.py --date 2026-07-19
    uv run --active ./scripts/trigger_ingest_aemo_nem.py --month 2026-05  # whole archived month

`--date` fetches one AEST calendar day, from Current if it's within
the last ~60 days, else falling back to the NEMWeb Archive
(https://www.nemweb.com.au/Reports/Archive/Daily_Reports/) automatically.
`--month` goes straight to the Archive for a whole calendar month in
one download — use this instead of looping `--date` over every day of
an already-archived month (e.g. backfilling last quarter).

Note: unlike openelectricity, there's no pandera validator for this
source yet (services/data-pipeline/src/ecolens/ingestion/validators/aemo.py
is still an empty stub) — docs go straight from fetch to upsert.
"""

import argparse
import asyncio
import uuid
from datetime import date, datetime

import httpx

from ecolens.ingestion.sources.aemo_nem import AEMONEMFetcher
from ecolens.ingestion.storage import duckdb_store
from ecolens.shared.observability.logging import get_logger

log = get_logger("trigger_ingest_aemo_nem")


def _year_month(value: str) -> tuple[int, int]:
    parsed = datetime.strptime(value, "%Y-%m")
    return parsed.year, parsed.month


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="AEST calendar day to fetch, YYYY-MM-DD (default: yesterday)",
    )
    group.add_argument(
        "--month",
        type=_year_month,
        default=None,
        help="Whole calendar month to fetch from the NEMWeb Archive, YYYY-MM",
    )
    return parser.parse_args()


async def run(for_date: date | None, for_month: tuple[int, int] | None) -> None:
    run_id = uuid.uuid4().hex
    fetcher = AEMONEMFetcher()
    async with httpx.AsyncClient(timeout=300) as client:
        if for_month is not None:
            year, month = for_month
            docs = await fetcher.fetch_month(client, year, month)
        else:
            docs = await fetcher.fetch_for_date(client, for_date)

    log.info("fetch.complete", run_id=run_id, doc_count=len(docs))
    if not docs:
        log.warning("fetch.empty", run_id=run_id)
        return

    written = duckdb_store.write_historical("aemo_nem", docs, run_id=run_id)
    log.info("duckdb.write_complete", run_id=run_id, written=written)


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(args.date, args.month))
