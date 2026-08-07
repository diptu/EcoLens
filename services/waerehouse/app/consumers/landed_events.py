"""Handles one `publish_landed_event` message off `Settings.
rabbitmq_landing_queue` — this service's own version of `data-pipeline`'s
`pipeline.warehouse_sync.sync_landed_event`, adapted for `services/
ingestion`'s newer shared-DuckDB-file staging shape (`app.db.
duckdb_client.read_run_with_fallback`, not the legacy one-file-per-run
layout — falls back to `services/ingestion`'s object-storage snapshot
when the shared `duckdb_staging` volume isn't actually shared, i.e.
`services/ingestion` is running on a different machine than this
consumer).

On success: reads this run's rows out of the shared DuckDB file, bulk-
loads them into Postgres `raw.*` (`loaders.postgres_loader.
load_to_postgres`), closes `meta._ingest_log` out to `"success"` with the
real `rows_loaded`. On failure: closes it out to `"sync_failed"` and
re-raises — `app.db.rabbitmq.consume_landed_events` is what actually
dead-letters/acks around this, this function's only job is "do the sync,
raise if it didn't work".
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from app.core.logging import get_logger, set_run_id
from app.core.metrics import consume_duration_seconds, rows_loaded_total
from app.db.duckdb_client import read_run_with_fallback
from app.db.session import get_session
from app.loaders.ingest_log import mark_sync_failed, mark_synced
from app.loaders.postgres_loader import load_to_postgres

log = get_logger(__name__)


async def sync_landed_event(payload: dict[str, Any]) -> None:
    run_id = uuid.UUID(payload["run_id"])
    set_run_id(str(run_id))
    source = payload["source"]
    table = payload["table"]
    schema = payload.get("schema", "raw")
    object_storage_key = payload.get("object_storage_key")
    object_storage_bucket = payload.get("object_storage_bucket")

    started = time.monotonic()
    try:
        df = await read_run_with_fallback(
            table, str(run_id), object_storage_key, object_storage_bucket
        )
        async with get_session() as session:
            rows_loaded = await load_to_postgres(session, df, table, schema=schema)
            await mark_synced(session, run_id, rows_loaded)
        rows_loaded_total.labels(source=source).inc(rows_loaded)
        log.info(
            "warehouse.sync_succeeded",
            source=source,
            table=table,
            rows_loaded=rows_loaded,
        )
    except Exception as exc:
        async with get_session() as session:
            await mark_sync_failed(session, run_id, str(exc))
        log.error(
            "warehouse.sync_failed",
            source=source,
            table=table,
            error=str(exc),
        )
        raise
    finally:
        consume_duration_seconds.labels(source=source).observe(
            time.monotonic() - started
        )
