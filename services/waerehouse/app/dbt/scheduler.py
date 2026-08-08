"""Shared `dbt build`-trigger logic -- `api/v1/dbt/routes.py`'s
`POST /v1/dbt/build` (dashboard-triggered) and `consumers.landed_events`'s
automatic post-landing trigger (`TODO.md`'s "Scheduled Execution Runner")
both go through `run_build` below, so there's exactly one lock-acquire /
run / log-finish / training-trigger-publish sequence, not two copies that
could drift.

**Concurrent-build lock**: an atomic `INSERT ... WHERE NOT EXISTS` against
`meta._dbt_build_log` itself (no Redis dependency in this service) --
see `run_build`'s own docstring for the full reasoning, ported from
`api/v1/dbt/routes.py`'s original version of this logic.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from opentelemetry.trace import Status, StatusCode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.tracing import get_tracer
from app.dbt.runner import run_dbt
from app.dbt.training_trigger import publish_training_triggers_for_build

log = get_logger(__name__)
tracer = get_tracer()

_STALE_LOCK_MINUTES = 30


async def _try_start_build(
    db: AsyncSession, *, run_id: str, target: str, trigger: str, triggered_by: str
) -> bool:
    """Atomically inserts a `running` row iff no other `running` row
    younger than `_STALE_LOCK_MINUTES` already exists -- the lock
    acquisition itself. Returns whether it succeeded (`True`) or another
    build is genuinely still in progress (`False`)."""
    result = await db.execute(
        text(
            "INSERT INTO meta._dbt_build_log "
            "(id, subcommand, target, trigger, triggered_by, status, started_at) "
            "SELECT :id, 'build', :target, :trigger, :triggered_by, 'running', :started_at "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM meta._dbt_build_log "
            "  WHERE status = 'running' "
            "    AND started_at > now() - make_interval(mins => :stale_minutes)"
            ") "
            "RETURNING id"
        ),
        {
            "id": run_id,
            "target": target,
            "trigger": trigger,
            "triggered_by": triggered_by,
            "started_at": datetime.now(UTC),
            "stale_minutes": _STALE_LOCK_MINUTES,
        },
    )
    acquired = result.first() is not None
    await db.commit()
    return acquired


async def _log_build_finish(
    db: AsyncSession, *, run_id: str, exit_code: int, error: str | None
) -> None:
    status = "success" if exit_code == 0 else "failed"
    await db.execute(
        text(
            "UPDATE meta._dbt_build_log "
            "SET status = :status, finished_at = :finished_at, exit_code = :exit_code, error = :error "
            "WHERE id = :id"
        ),
        {
            "status": status,
            "finished_at": datetime.now(UTC),
            "exit_code": exit_code,
            "error": error,
            "id": run_id,
        },
    )
    await db.commit()


async def run_build(
    db: AsyncSession, *, trigger: str, triggered_by: str, target: str = "dev"
) -> tuple[int, str] | None:
    """Acquires the build lock, runs `dbt build`, logs the outcome, and
    (on success) publishes the incremental-training-trigger events --
    the exact sequence `POST /v1/dbt/build` used to run inline. Returns
    `(exit_code, run_id)` if a build actually ran, or `None` if the lock
    was already held (another build is genuinely in progress) -- the
    caller decides what `None` means for it (a 409 for an HTTP caller,
    a quiet skip for the scheduled trigger below).
    """
    run_id = str(uuid.uuid4())
    with tracer.start_as_current_span(
        "warehouse.dbt_build",
        attributes={"trigger": trigger, "triggered_by": triggered_by, "target": target},
    ) as span:
        span.set_attribute("run_id", run_id)
        acquired = await _try_start_build(
            db, run_id=run_id, target=target, trigger=trigger, triggered_by=triggered_by
        )
        if not acquired:
            span.set_attribute("lock_acquired", False)
            return None

        # `run_dbt` is a synchronous subprocess call -- offload it so this
        # doesn't block the event loop other work is being served on
        # (a request/response cycle for the HTTP route, the RabbitMQ
        # consume loop for the scheduled trigger).
        exit_code, output = await asyncio.to_thread(run_dbt, "build", target=target)
        span.set_attribute("exit_code", exit_code)

        error = None if exit_code == 0 else output[-2000:]
        if error is not None:
            span.set_status(Status(StatusCode.ERROR, f"dbt build exited {exit_code}"))
        await _log_build_finish(db, run_id=run_id, exit_code=exit_code, error=error)

        if exit_code == 0:
            await publish_training_triggers_for_build(triggered_by=triggered_by)

        return exit_code, run_id


async def trigger_build_if_due(db: AsyncSession) -> bool:
    """`consumers.landed_events.sync_landed_event`'s own hook -- called
    (fire-and-forget, never awaited inline in the consume loop) after
    every successfully-synced landed event. Runs a real `dbt build` only
    if the most recent build attempt (any status -- `running`/`success`/
    `failed` all count, so a currently-running or just-finished build
    doesn't immediately queue a second one) is older than
    `Settings.scheduled_build_min_interval_minutes`, or none has ever
    run. Returns whether a build was actually triggered (for tests/
    logging, not consumed by the caller).
    """
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(
        minutes=settings.scheduled_build_min_interval_minutes
    )
    result = await db.execute(
        text(
            "SELECT started_at FROM meta._dbt_build_log "
            "ORDER BY started_at DESC LIMIT 1"
        )
    )
    row = result.first()
    if row is not None and row[0] >= cutoff:
        return False

    outcome = await run_build(db, trigger="scheduled", triggered_by="landed_event")
    if outcome is None:
        # Another build (dashboard-triggered or a race with a sibling
        # consumer process) is already running -- not an error, just
        # nothing to do this time.
        return False

    exit_code, run_id = outcome
    log.info(
        "dbt.scheduled_build_triggered",
        run_id=run_id,
        exit_code=exit_code,
        min_interval_minutes=settings.scheduled_build_min_interval_minutes,
    )
    return True
