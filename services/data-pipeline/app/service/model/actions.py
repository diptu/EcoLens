"""`POST /v1/model/train` (Model Operations TODO.md Phase 2).

Publishes the same `warehouse.transform.completed`-shaped RabbitMQ
event `pipeline.flows.publish_training_trigger` fires automatically
after a successful dbt build -- just on demand, from an HTTP call
instead of a Prefect flow. `app.service.training_worker`'s consumer
needs no changes: it already handles this event regardless of what
published it.

Calls `publish_training_trigger.fn(...)` -- the Prefect `@task`'s
undecorated function -- instead of the decorated task itself, so this
runs as a plain coroutine (no Prefect orchestration/task-run tracking,
which needs a flow-run context an HTTP request handler isn't) while
still sharing the exact same payload-building logic the automatic path
uses, not a second copy of it.

No "training already in progress" guard, unlike `trigger_run`/
`trigger_backfill` -- those hold their lock/DB-row for the exact
duration the *same process* awaits the work, so releasing it on
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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.schemas.model import TrainingRunOut, TrainTriggerResponse
from app.service.pipeline.flows import publish_training_trigger


async def trigger_training(
    regions: list[str] | None,
    window_hours: int | None,
    *,
    triggered_by: str,
) -> TrainTriggerResponse:
    settings = get_settings()
    resolved_regions = regions or settings.model_default_regions
    resolved_window_hours = window_hours or settings.incremental_train_window_hours

    payload = await publish_training_trigger.fn(
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
    actual "is a training run in flight right now" signal (Model
    Operations TODO.md Phase 4), written by `training_worker.
    handle_training_trigger`."""
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
            # into a list, but a raw text() query doesn't guarantee it --
            # same normalisation `datasources.service._normalise_config_row`
            # applies to `metadata`.
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
