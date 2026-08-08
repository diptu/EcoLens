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
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.rabbitmq import publish_training_trigger_event
from app.db.session import get_session
from app.schemas.model import TrainingRunOut, TrainTriggerResponse


async def _build_and_publish_training_trigger(
    regions: list[str], window_hours: int, *, triggered_by: str
) -> dict:
    """Same payload shape `services/waerehouse`'s identical function
    builds -- see that module's docstring for the full field-by-field
    reasoning. This service's own copy exists only because
    `POST /v1/model/train` is a manual trigger this API process needs
    to publish itself, not because the automatic path lives here too
    (it doesn't -- `services/waerehouse` owns `dbt build` now)."""
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
        "architecture": "lstm",
        "triggered_by": triggered_by,
    }
    await publish_training_trigger_event(payload)
    return payload


async def trigger_training(
    regions: list[str] | None,
    window_hours: int | None,
    *,
    triggered_by: str,
) -> TrainTriggerResponse:
    settings = get_settings()
    resolved_regions = regions or settings.model_default_regions
    resolved_window_hours = window_hours or settings.incremental_train_window_hours

    payload = await _build_and_publish_training_trigger(
        resolved_regions, resolved_window_hours, triggered_by="manual"
    )

    return TrainTriggerResponse(
        queued_at=payload["occurred_at"],
        regions=payload["regions"],
        window_since=payload["window_since"],
        window_until=payload["window_until"],
        anomalies_flagged=payload["anomalies_flagged"],
        triggered_by=triggered_by,
    )


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
