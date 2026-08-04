"""Training-trigger consumer entrypoint (`ecolens-pipeline train-worker`,
the `train-worker` docker-compose service) — `TODO.md`'s "Event-Driven
Pipeline Trigger for Online/Incremental Model Training", item 3's
"resilient message consumer... in the forecasting service". Per
`README.md`'s own service-boundary rule ("`forecast-api` never trains")
this lives in `data-pipeline`, the service that already owns `ml/train.py`,
MLflow, and the warehouse connection — not in `forecast-api`.

Structurally identical to `app.service.worker` (the warehouse-sync consumer):
a long-running RabbitMQ consume loop wired to a per-message handler,
meant to run as its own OS process (own container, own docker-compose
service), never inside `forecast-api`'s request/response cycle. This is
what satisfies `TODO.md`'s "Non-Blocking Training Architecture" item 5's
core requirement ("never run a training loop synchronously inside
forecast-api's request/response cycle") in practice: training here is not
reachable from any HTTP handler in either service at all, by construction
— the same guarantee `app.service.worker`'s warehouse-sync consumer already
gives the ingestion path, not a new mechanism invented for this feature.

See `ml.incremental.train_and_register_incremental` for the actual
warm-started fine-tune, and `mq.rabbitmq_client.
consume_training_trigger_events` for the consume loop / DLX behavior on a
failed handler call.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pandas as pd
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_session
from app.service.ml.incremental import train_and_register_incremental
from app.db.rabbitmq import close_rabbitmq, consume_training_trigger_events
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


async def _log_training_start(
    model_name: str,
    triggered_by: str,
    regions: list[str],
    window_start,
    window_end,
) -> uuid.UUID:
    """Insert a 'running' row into `meta._training_log` (Model Operations
    TODO.md Phase 4) -- mirrors `pipeline.tasks._common._log_run_start`'s
    pattern for `meta._ingest_log`. Returns the row id."""
    log_id = uuid.uuid4()
    async with get_session() as session:
        await session.execute(
            text(
                """
                INSERT INTO meta._training_log
                    (id, model_name, status, triggered_by, regions, window_start, window_end, started_at, hostname)
                VALUES
                    (:id, :model_name, 'running', :triggered_by, CAST(:regions AS jsonb), :window_start, :window_end, now(), :hostname)
                """
            ),
            {
                "id": str(log_id),
                "model_name": model_name,
                "triggered_by": triggered_by,
                "regions": json.dumps(regions),
                "window_start": window_start,
                "window_end": window_end,
                "hostname": get_settings().hostname,
            },
        )
    return log_id


async def _log_training_finish(
    log_id: uuid.UUID,
    *,
    status: str,
    run_id: str | None = None,
    model_version: str | None = None,
    error_message: str | None = None,
) -> None:
    """Close out a `meta._training_log` row as `'success'`/`'failed'`."""
    async with get_session() as session:
        await session.execute(
            text(
                """
                UPDATE meta._training_log
                SET finished_at = now(),
                    status = :status,
                    run_id = :run_id,
                    model_version = :model_version,
                    error_message = :error_message
                WHERE id = :id
                """
            ),
            {
                "id": str(log_id),
                "status": status,
                "run_id": run_id,
                "model_version": model_version,
                "error_message": error_message[:500] if error_message else None,
            },
        )


async def handle_training_trigger(payload: dict[str, Any]) -> None:
    """Handle one `publish_training_trigger_event` message
    (`pipeline.flows.publish_training_trigger`'s payload shape): resolve
    the data window and regions from the event, run the incremental
    fine-tune, and let any failure (no warm-startable version yet, empty
    window, a bad/malformed payload) propagate — `consume_training_
    trigger_events`'s `message.process()` nacks on exception, which,
    because the queue's `x-dead-letter-exchange` is set, dead-letters the
    message into `rabbitmq_training_trigger_dlq` rather than silently
    dropping it or retrying forever.

    Logs a `meta._training_log` row for the full attempt regardless of
    outcome (`running` at start, `success`/`failed` at the end) -- the
    real "is a training run in flight right now" signal `GET /v1/model/
    training-runs` reads, since nothing logged that anywhere before
    (Model Operations TODO.md Phase 4).
    """
    settings = get_settings()
    regions = payload.get("regions") or settings.model_default_regions
    window_since = payload.get("window_since")
    window_until = payload.get("window_until")
    since = (
        pd.Timestamp(window_since)
        if window_since
        else pd.Timestamp.now(tz="UTC")
        - pd.Timedelta(hours=settings.incremental_train_window_hours)
    )
    until = pd.Timestamp(window_until) if window_until else pd.Timestamp.now(tz="UTC")
    model_name = settings.mlflow_registry_model_name
    triggered_by = payload.get("triggered_by") or "schedule"

    log_id = await _log_training_start(
        model_name,
        triggered_by,
        list(regions),
        since.to_pydatetime(),
        until.to_pydatetime(),
    )
    try:
        result = await train_and_register_incremental(model_name, regions, since)
    except Exception as exc:
        await _log_training_finish(log_id, status="failed", error_message=str(exc))
        raise

    await _log_training_finish(
        log_id,
        status="success",
        run_id=result.run_id,
        model_version=result.model_version,
    )
    log.info(
        "training_worker.incremental_trained",
        model_name=model_name,
        run_id=result.run_id,
        model_version=result.model_version,
        regions=regions,
    )


async def run() -> None:
    """Run forever, running an incremental training pass as each
    training-trigger event arrives. Exits (and closes the connection) on
    cancellation/interrupt."""
    configure_logging()
    log.info("training_worker.consumer_starting")
    try:
        await consume_training_trigger_events(handle_training_trigger)
    finally:
        await close_rabbitmq()
        log.info("training_worker.consumer_stopped")
