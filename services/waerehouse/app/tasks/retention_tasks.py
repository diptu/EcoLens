"""Celery task wrapper around `retention.cold_storage.export_and_prune`
+ `retention.vacuum.vacuum_analyze_raw_tables` — the scheduled half of
root `TODO.md`'s "Vacuum Database" item (`app.celery_app`'s
`beat_schedule` is what actually invokes this, daily).

Deliberately thin, same shape as `services/ingestion`'s
`celery_tasks.py`: the CLI (`cli.py`'s `export-and-prune`/`vacuum`
commands) and Celery Beat both go through the exact same real
`retention.*` functions, not a separate scheduled-only code path.

Logs to `meta._retention_log` (`0004_retention_log.sql`) — same
start/finish audit-trail pattern `dbt/scheduler.py`'s `_try_start_build`/
`_log_build_finish` already use for `meta._dbt_build_log`, added so the
dashboard's Scheduled Operations row for this job has real `last_run_at`/
history to show, not just a schedule string (root `TODO.md`'s "Scheduled
Operations" item's own retention-visibility follow-up).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.celery_app import celery_app, run_async
from app.core.logging import configure_logging, get_logger
from app.db.session import get_session

log = get_logger(__name__)


async def _log_retention_start(*, trigger: str, triggered_by: str) -> uuid.UUID:
    run_id = uuid.uuid4()
    async with get_session() as db:
        await db.execute(
            text(
                "INSERT INTO meta._retention_log "
                "(id, trigger, triggered_by, status, started_at) "
                "VALUES (:id, :trigger, :triggered_by, 'running', :started_at)"
            ),
            {
                "id": str(run_id),
                "trigger": trigger,
                "triggered_by": triggered_by,
                "started_at": datetime.now(UTC),
            },
        )
        await db.commit()
    return run_id


async def _log_retention_finish(
    run_id: uuid.UUID,
    *,
    status: str,
    pruned: dict[str, object] | None = None,
    vacuumed: list[str] | None = None,
    error: str | None = None,
) -> None:
    import json

    async with get_session() as db:
        await db.execute(
            text(
                "UPDATE meta._retention_log "
                "SET status = :status, finished_at = :finished_at, "
                "    pruned = :pruned, vacuumed = :vacuumed, error = :error "
                "WHERE id = :id"
            ),
            {
                "id": str(run_id),
                "status": status,
                "finished_at": datetime.now(UTC),
                "pruned": json.dumps(pruned) if pruned is not None else None,
                "vacuumed": json.dumps(vacuumed) if vacuumed is not None else None,
                "error": error,
            },
        )
        await db.commit()


@celery_app.task(name="app.tasks.retention_tasks.export_and_prune_and_vacuum_task")
def export_and_prune_and_vacuum_task(
    days: int | None = None, triggered_by: str = "schedule"
) -> dict[str, object]:
    """Exports + prunes rows older than `days` (`Settings.retention_days`
    if omitted, itself `.env`-configurable — the "older data defined in
    .env file" root `TODO.md` names), then `VACUUM ANALYZE`s only if
    anything was actually pruned (an empty prune means nothing to
    reclaim space from). Real per-run audit trail in `meta._retention_log`
    (`_log_retention_start`/`_finish` above), same convention `meta.
    _dbt_build_log` already uses for dbt builds — this is what backs the
    dashboard's Scheduled Operations row for this job.
    """
    configure_logging()
    from app.retention.cold_storage import export_and_prune
    from app.retention.vacuum import vacuum_analyze_raw_tables

    run_id = run_async(_log_retention_start(trigger="scheduled", triggered_by=triggered_by))
    log.info("retention_tasks.export_and_prune_started", run_id=str(run_id), days=days)
    try:
        pruned = run_async(export_and_prune(days))
    except Exception as exc:
        log.error("retention_tasks.export_and_prune_failed", run_id=str(run_id), error=str(exc))
        run_async(_log_retention_finish(run_id, status="failed", error=str(exc)[:2000]))
        raise
    log.info("retention_tasks.export_and_prune_finished", run_id=str(run_id), results=pruned)

    total_pruned = sum(counts["pruned"] for counts in pruned.values())
    vacuumed: list[str] = []
    if total_pruned > 0:
        try:
            vacuumed = run_async(vacuum_analyze_raw_tables())
        except Exception as exc:
            log.error("retention_tasks.vacuum_failed", run_id=str(run_id), error=str(exc))
            run_async(
                _log_retention_finish(
                    run_id, status="failed", pruned=pruned, error=str(exc)[:2000]
                )
            )
            raise
        log.info("retention_tasks.vacuum_finished", run_id=str(run_id), tables=vacuumed)
    else:
        log.info("retention_tasks.vacuum_skipped", run_id=str(run_id), reason="nothing pruned")

    run_async(
        _log_retention_finish(run_id, status="success", pruned=pruned, vacuumed=vacuumed)
    )
    return {"pruned": pruned, "vacuumed": vacuumed}
