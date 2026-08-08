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
real `rows_loaded` -- then fires `_trigger_scheduled_build_in_background`
(`TODO.md`'s "Scheduled Execution Runner": a real `dbt build` triggered
by new data actually landing, debounced by `app.dbt.scheduler.
trigger_build_if_due` so 5 sources landing in the same ingestion cycle
don't queue 5 back-to-back builds). On failure: closes it out to
`"sync_failed"` and re-raises — `app.db.rabbitmq.consume_landed_events`
is what actually dead-letters/acks around this, this function's only job
is "do the sync, raise if it didn't work".
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from opentelemetry.trace import Status, StatusCode

from app.core.logging import get_logger, set_run_id
from app.core.metrics import consume_duration_seconds, rows_loaded_total
from app.core.tracing import get_tracer
from app.db.duckdb_client import read_run_with_fallback
from app.db.session import get_session
from app.dbt.scheduler import trigger_build_if_due
from app.loaders.ingest_log import mark_sync_failed, mark_synced
from app.loaders.postgres_loader import load_to_postgres

log = get_logger(__name__)
tracer = get_tracer()


def _trigger_scheduled_build_in_background() -> None:
    """Fire-and-forget -- never awaited inline in the consume loop.
    A `dbt build` can run for tens of seconds; blocking message
    processing on it here would mean this consumer can't pick up the
    *next* landed event until the current build finishes, defeating the
    whole point of a debounced, best-effort trigger. A failure here is
    logged by `trigger_build_if_due`'s own callers' error handling
    inside the task itself -- it must never propagate back into (or
    fail) the message handler that's already succeeded by this point.
    """

    async def _run() -> None:
        try:
            async with get_session() as session:
                await trigger_build_if_due(session)
        except Exception as exc:  # noqa: BLE001 - a failed scheduled build must never affect the already-successful sync this was triggered from
            log.error("dbt.scheduled_build_trigger_failed", error=str(exc))

    asyncio.ensure_future(_run())


async def sync_landed_event(payload: dict[str, Any]) -> None:
    run_id = uuid.UUID(payload["run_id"])
    set_run_id(str(run_id))
    source = payload["source"]
    table = payload["table"]
    schema = payload.get("schema", "raw")
    object_storage_key = payload.get("object_storage_key")
    object_storage_bucket = payload.get("object_storage_bucket")

    started = time.monotonic()
    with tracer.start_as_current_span(
        "warehouse.sync_landed_event",
        attributes={"source": source, "table": table, "run_id": str(run_id)},
    ) as span:
        try:
            df = await read_run_with_fallback(
                table, str(run_id), object_storage_key, object_storage_bucket
            )
            async with get_session() as session:
                rows_loaded = await load_to_postgres(session, df, table, schema=schema)
                await mark_synced(session, run_id, rows_loaded)
            span.set_attribute("rows_loaded", rows_loaded)
            rows_loaded_total.labels(source=source).inc(rows_loaded)
            log.info(
                "warehouse.sync_succeeded",
                source=source,
                table=table,
                rows_loaded=rows_loaded,
            )
            _trigger_scheduled_build_in_background()
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
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
