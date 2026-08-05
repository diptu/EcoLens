"""Consumer-side half of the raw-landing pipeline (`overview.md` §2
Event-Driven Warehousing): RabbitMQ event -> read the DuckDB-staged
DataFrame -> load it into Postgres `raw.*` -> close out `meta._ingest_log`.

The producer side (`pipeline.tasks._common.standard_run`, via `pipeline.
duckdb_staging.stage_dataframe` + `mq.rabbitmq_client.publish_landed_event`)
is what puts a message on `Settings.rabbitmq_landing_queue` in the first
place. `sync_landed_event` is the handler `mq.rabbitmq_client.
consume_landed_events` calls per message — see `app.service.worker` / the
`ecolens-pipeline worker` CLI command / the `warehouse-sync`
docker-compose service for what actually runs the consume loop.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.db.session import get_session
from app.core.logging import get_logger, set_run_id
from app.service.pipeline.duckdb_staging import delete_staged, read_staged
from app.service.pipeline.landing import load_to_postgres
from app.service.pipeline.tasks._common import log_run_sync_failed, log_run_synced

log = get_logger(__name__)


async def sync_landed_event(payload: dict[str, Any]) -> None:
    """Handle one `publish_landed_event` message.

    On success: `meta._ingest_log` moves `"staged"` -> `"success"` with
    the real `rows_loaded`, and the DuckDB file is deleted (its job as
    the audit/replay artifact is done once the row is durably in
    Postgres).

    On failure: `meta._ingest_log` moves to `"sync_failed"` and the
    DuckDB file is deliberately left on disk — it's the recovery
    artifact for a manual retry (same role the old S3-Parquet-replay
    playbook in `pipeline/tasks/task.md` served). Re-raises so `mq.
    rabbitmq_client.consume_landed_events`' `message.process()` nacks
    the message rather than acking a run that didn't actually sync.
    """
    run_id = uuid.UUID(payload["run_id"])
    set_run_id(str(run_id))
    source = payload["source"]
    table = payload["table"]
    schema = payload.get("schema", "raw")
    duckdb_path = payload["duckdb_path"]

    try:
        df = read_staged(duckdb_path, table, str(run_id))
        async with get_session() as session:
            rows_loaded = await load_to_postgres(session, df, table, schema=schema)
        await log_run_synced(run_id, rows_loaded)
        delete_staged(duckdb_path, table, str(run_id))
        log.info(
            "warehouse.sync_succeeded",
            source=source,
            run_id=str(run_id),
            table=table,
            rows_loaded=rows_loaded,
        )
    except Exception as exc:
        await log_run_sync_failed(run_id, str(exc))
        log.error(
            "warehouse.sync_failed",
            source=source,
            run_id=str(run_id),
            table=table,
            duckdb_path=duckdb_path,
            error=str(exc),
        )
        raise
