"""`POST /v1/model/train` -- manually publish a training-trigger event,
the same shape `services/waerehouse`'s `dbt.training_trigger.
publish_training_trigger` fires automatically after a successful dbt
build. Ported from data-pipeline's identical module as part of the
training-code migration -- the payload-building logic (window calc,
real `meta.anomalies` count) is duplicated here rather than imported
from `services/waerehouse` (separate service, separate deployable, same
cross-service duplication convention `service/ml/features.py` etc.
already establish), not delegated to a Prefect task the way data-
pipeline's original did (this service has no Prefect dependency).
`app.db.rabbitmq.publish_training_trigger_event` needs no changes: it
already handles this event regardless of what published it.

**`meta.anomalies` reads here use the primary `get_session`, not
`get_log_session`** -- unlike `log_training_start`/`log_training_finish`/
`list_training_runs` below (`meta._training_log`, correctly on
`LOG_DB_URL`), `meta.anomalies` is a real dbt source feeding a live
dashboard chart and must stay reachable from the primary database dbt
actually connects to. See `services/ingestion`'s `app.service.
datasources.service.fetch_run_rows` docstring for the full real story.

No "training already in progress" guard, unlike ingestion's
`trigger_run`/`trigger_backfill` -- those hold their lock/DB-row for the
exact duration the *same process* awaits the work, so releasing it on
completion is straightforward. Training happens in a separate,
independently-running consumer process (`train-worker`) this API
process never talks to directly and has no completion signal from, so
there's no real place to hang a "clear this when it's done" hook.
Multiple manual triggers simply queue multiple fine-tune events, which
the worker's single consume loop processes one at a time -- redundant
in the worst case, never conflicting.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.rabbitmq import publish_training_trigger_event
from app.db.session import get_log_session, get_session
from app.schemas.model import TrainingRunOut, TrainTriggerResponse


async def _build_and_publish_training_trigger(
    regions: list[str],
    window_hours: int,
    *,
    triggered_by: str,
    architecture: str = "lstm",
    full_retrain: bool = False,
) -> dict:
    """Same payload shape `services/waerehouse`'s identical function
    builds -- see that module's docstring for the full field-by-field
    reasoning. This service's own copy exists only because
    `POST /v1/model/train` is a manual trigger this API process needs
    to publish itself, not because the automatic path lives here too
    (it doesn't -- `services/waerehouse` owns `dbt build` now).

    `architecture` used to be hardcoded to `"lstm"` regardless of the
    caller's request -- selecting TFT or TimesFM in the dashboard's
    Fine-tune form and submitting silently fine-tuned LSTM instead. Now
    threaded through from `trigger_training`'s own `architecture` param."""
    window_until = datetime.now(UTC)
    window_since = window_until - timedelta(hours=window_hours)
    async with get_session() as db:
        row = (
            await db.execute(
                text("SELECT count(*) FROM meta.anomalies WHERE detected_at >= :since"),
                {"since": window_since},
            )
        ).first()
    anomalies_flagged = int(row[0]) if row is not None else 0

    payload = {
        "event": "warehouse.transform.completed",
        "occurred_at": window_until.isoformat(),
        "dataset": "raw_marts.fct_energy_demand",
        "regions": regions,
        "window_since": window_since.isoformat(),
        "window_until": window_until.isoformat(),
        "anomalies_flagged": anomalies_flagged,
        "architecture": architecture,
        "triggered_by": triggered_by,
        "full_retrain": full_retrain,
    }
    await publish_training_trigger_event(payload)
    return payload


async def trigger_training(
    regions: list[str] | None,
    window_hours: int | None,
    *,
    triggered_by: str,
    architecture: str | None = None,
    full_retrain: bool = False,
) -> TrainTriggerResponse:
    """Real bug, confirmed live 2026-08-11: this used to hardcode
    `triggered_by="manual"` in the call below regardless of the
    `triggered_by` this function was actually given (`routes.py`'s
    `trigger_training_endpoint` passes `"public"`) -- so the
    `TrainTriggerResponse` the caller got back said `"public"` while the
    published event, and therefore `meta._training_log.triggered_by`
    (`training_worker.handle_training_trigger`'s
    `payload.get("triggered_by")`), always said `"manual"` instead. Any
    caller trying to correlate its own trigger response with the
    resulting training-run row by `triggered_by` (the dashboard's
    Fine-tune form, once it started polling `GET /v1/model/training-runs`
    for real progress) could never find a match. Now the same value
    flows through end to end."""
    settings = get_settings()
    resolved_regions = regions or settings.model_default_regions
    resolved_window_hours = window_hours or settings.incremental_train_window_hours
    resolved_architecture = architecture or "lstm"

    payload = await _build_and_publish_training_trigger(
        resolved_regions,
        resolved_window_hours,
        triggered_by=triggered_by,
        architecture=resolved_architecture,
        full_retrain=full_retrain,
    )

    return TrainTriggerResponse(
        queued_at=payload["occurred_at"],
        regions=payload["regions"],
        window_since=payload["window_since"],
        window_until=payload["window_until"],
        anomalies_flagged=payload["anomalies_flagged"],
        triggered_by=triggered_by,
        architecture=payload["architecture"],
        full_retrain=payload["full_retrain"],
    )


async def log_training_start(
    model_name: str,
    triggered_by: str,
    regions: list[str],
    window_start,
    window_end,
) -> uuid.UUID:
    """Insert a 'running' row into `meta._training_log` -- mirrors
    `services/waerehouse`'s `_try_start_build`'s pattern for
    `meta._dbt_build_log`. Returns the row id.

    Shared by `training_worker.handle_training_trigger` (the RabbitMQ-
    triggered LSTM/TFT path) and `train_energy_forecast.
    train_and_register_energy_forecast` (the CLI-triggered
    `energy_forecast_multi_task` path) -- previously private to
    `training_worker.py` only, so CLI-invoked energy-forecast runs never
    showed up in `GET /v1/model/training-runs` (the dashboard's Training
    Jobs tab) at all. Moved here rather than duplicated -- both callers
    are the same service, unlike the deliberate cross-service
    duplication convention `service/ml/features.py` etc. use.

    `get_session()`'s own docstring calls this service "read-only" and
    its context manager never commits (`session.close()` in a `finally`
    only) -- true for every other caller, but not this one. Confirmed
    live: without the explicit `commit()` below, this INSERT never
    actually persisted (`GET /v1/model/training-runs` stayed empty after
    a real training run) even though `execute()` raised no error --
    SQLAlchemy's async session opens an implicit transaction on first
    `execute()` and silently rolls it back on close without one."""
    log_id = uuid.uuid4()
    async with get_log_session() as session:
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
        await session.commit()
    return log_id


async def log_training_finish(
    log_id: uuid.UUID,
    *,
    status: str,
    run_id: str | None = None,
    model_version: str | None = None,
    error_message: str | None = None,
) -> None:
    """Close out a `meta._training_log` row as `'success'`/`'failed'` --
    see `log_training_start`'s docstring for why the explicit `commit()`
    below is required, not optional."""
    async with get_log_session() as session:
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
        await session.commit()


async def list_training_runs(db: AsyncSession, limit: int = 20) -> list[TrainingRunOut]:
    """Real `meta._training_log` history, newest first -- backs
    `GET /v1/model/training-runs`. A `status == "running"` row is the
    actual "is a training run in flight right now" signal, written by
    `training_worker.handle_training_trigger`."""
    result = await db.execute(
        text(
            "SELECT id, model_name, status, triggered_by, regions, window_start, "
            "window_end, started_at, finished_at, run_id, model_version, error_message "
            "FROM meta._training_log ORDER BY started_at DESC LIMIT :limit"
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()
    return [
        TrainingRunOut(
            id=str(row["id"]),
            model_name=row["model_name"],
            status=row["status"],
            triggered_by=row["triggered_by"],
            # asyncpg/SQLAlchemy usually hand back jsonb already parsed
            # into a list, but a raw text() query doesn't guarantee it.
            regions=json.loads(row["regions"])
            if isinstance(row["regions"], str)
            else row["regions"],
            window_start=row["window_start"],
            window_end=row["window_end"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            run_id=row["run_id"],
            model_version=row["model_version"],
            error_message=row["error_message"],
        )
        for row in rows
    ]
