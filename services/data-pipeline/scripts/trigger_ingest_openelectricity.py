"""Manually trigger one OpenElectricity fetch -> DuckDB upsert.

Standalone script (not a pytest test): fetches the live NEM/WEM generation
mix and upserts it into the `openelectricity_responses` table. Run
directly:

    uv run --active ./scripts/trigger_ingest_openelectricity.py
"""

import asyncio
import uuid
from datetime import datetime, timezone

import httpx

import pandera.errors

from ecolens.config import get_settings
from ecolens.ingestion.core.data_source_overrides import is_source_enabled
from ecolens.ingestion.core.run_history import record_run
from ecolens.ingestion.service.openelectricity import OpenElectricityFetcher
from ecolens.ingestion.db import duckdb_store
from ecolens.ingestion.schema.validators.openelectricity import (
    validate as validate_docs,
)
from ecolens.shared.observability.logging import get_logger

log = get_logger("trigger_ingest_openelectricity")


async def run() -> None:
    if not is_source_enabled("openelectricity"):
        log.info("source.disabled", source="openelectricity", hint="skipping this run")
        return

    started_at = datetime.now(timezone.utc)
    run_id = uuid.uuid4().hex
    settings = get_settings()
    if not settings.oe_api_key:
        log.error("oe_api_key.missing", hint="set OE_API_KEY in .env")
        record_run(
            "openelectricity",
            status="failed",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            error="OE_API_KEY not configured",
            run_id=run_id,
        )
        return

    fetcher = OpenElectricityFetcher(api_key=settings.oe_api_key)
    async with httpx.AsyncClient(timeout=settings.oe_request_timeout_seconds) as client:
        docs = await fetcher.fetch(client)

    log.info("fetch.complete", run_id=run_id, doc_count=len(docs))

    try:
        docs = validate_docs(docs)
    except pandera.errors.SchemaError as e:
        log.error("validation.failed", run_id=run_id, error=str(e))
        record_run(
            "openelectricity",
            status="failed",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            records_fetched=len(docs),
            error=str(e),
            run_id=run_id,
        )
        return
    log.info("validation.passed", run_id=run_id, doc_count=len(docs))

    written = duckdb_store.write_historical("openelectricity", docs, run_id=run_id)
    log.info("duckdb.write_complete", run_id=run_id, written=written)
    anomalies_flagged = sum(1 for d in docs if d.get("anomaly_score", 0.0) > 0.0)
    record_run(
        "openelectricity",
        status="success",
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        records_fetched=len(docs),
        records_inserted=written,
        anomalies_flagged=anomalies_flagged,
        run_id=run_id,
    )


if __name__ == "__main__":
    asyncio.run(run())
