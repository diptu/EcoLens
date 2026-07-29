"""Manually trigger one AEMO WEM fetch -> DuckDB upsert.

Standalone script (not a pytest test): downloads one AWST calendar
day's WEMDE feeds (public, no API key) and upserts docs into the
`aemo_wem_dispatch` table. Run directly:

    uv run --active ./scripts/trigger_ingest_aemo_wem.py                # yesterday (AWST)
    uv run --active ./scripts/trigger_ingest_aemo_wem.py --date 2026-07-18

Note: demand (operationalDemandWithdrawal) tends to lag facilityScada/
price by an extra day — "yesterday" may show null demand_mw until it
catches up; pass an explicit --date two days back if you need demand.

Also unlike openelectricity, there's no pandera validator for this
source yet (services/data-pipeline/src/ecolens/ingestion/validators/aemo.py
is still an empty stub) — docs go straight from fetch to upsert.
"""

import argparse
import asyncio
import uuid
from datetime import date

import httpx

from ecolens.ingestion.service.aemo_wem import AEMOWEMFetcher
from ecolens.ingestion.db import duckdb_store
from ecolens.shared.observability.logging import get_logger

log = get_logger("trigger_ingest_aemo_wem")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="AWST calendar day to fetch, YYYY-MM-DD (default: yesterday)",
    )
    return parser.parse_args()


async def run(for_date: date | None) -> None:
    run_id = uuid.uuid4().hex
    fetcher = AEMOWEMFetcher()
    async with httpx.AsyncClient(timeout=60) as client:
        docs = await fetcher.fetch_for_date(client, for_date)

    log.info("fetch.complete", run_id=run_id, doc_count=len(docs))
    if not docs:
        log.warning("fetch.empty", run_id=run_id)
        return

    written = duckdb_store.write_historical("aemo_wem", docs, run_id=run_id)
    log.info("duckdb.write_complete", run_id=run_id, written=written)


if __name__ == "__main__":
    asyncio.run(run(parse_args().date))
