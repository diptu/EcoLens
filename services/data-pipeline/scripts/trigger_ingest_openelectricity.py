"""Manually trigger one OpenElectricity fetch -> DuckDB upsert.

Standalone script (not a pytest test): fetches the live NEM/WEM generation
mix and upserts it into the `openelectricity_responses` table. Run
directly:

    uv run --active ./scripts/trigger_ingest_openelectricity.py
"""

import asyncio
import uuid

import httpx

import pandera.errors

from ecolens.config import get_settings
from ecolens.ingestion.sources.openelectricity import OpenElectricityFetcher
from ecolens.ingestion.storage import duckdb_store
from ecolens.ingestion.validators.openelectricity import validate as validate_docs
from ecolens.shared.observability.logging import get_logger

log = get_logger("trigger_ingest_openelectricity")


async def run() -> None:
    settings = get_settings()
    if not settings.oe_api_key:
        log.error("oe_api_key.missing", hint="set OE_API_KEY in .env")
        return

    run_id = uuid.uuid4().hex
    fetcher = OpenElectricityFetcher(api_key=settings.oe_api_key)
    async with httpx.AsyncClient(timeout=settings.oe_request_timeout_seconds) as client:
        docs = await fetcher.fetch(client)

    log.info("fetch.complete", run_id=run_id, doc_count=len(docs))

    try:
        docs = validate_docs(docs)
    except pandera.errors.SchemaError as e:
        log.error("validation.failed", run_id=run_id, error=str(e))
        return
    log.info("validation.passed", run_id=run_id, doc_count=len(docs))

    written = duckdb_store.write_historical("openelectricity", docs, run_id=run_id)
    log.info("duckdb.write_complete", run_id=run_id, written=written)


if __name__ == "__main__":
    asyncio.run(run())
