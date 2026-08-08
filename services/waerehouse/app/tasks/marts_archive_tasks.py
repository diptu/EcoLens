"""Celery task wrapper around `retention.marts_archive.archive_and_prune_marts`
-- the scheduled half of root TODO.md's "save raw and raw.marts in
seperate database" item (`app.celery_app`'s `beat_schedule` is what
actually invokes this, daily).

Same shape as `app/tasks/retention_tasks.py`'s `export_and_prune_and_
vacuum_task`: the CLI (`cli.py`'s `archive-marts` command) and Celery
Beat both go through this exact same real `retention.marts_archive`
function, not a separate scheduled-only code path. Logs to `meta.
_marts_archive_log` (`0007_marts_archive_log.sql`).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.celery_app import celery_app, run_async
from app.core.logging import configure_logging, get_logger
from app.db.session import get_session

log = get_logger(__name__)


async def _log_archive_start(*, trigger: str, triggered_by: str) -> uuid.UUID:
    run_id = uuid.uuid4()
    async with get_session() as db:
        await db.execute(
            text(
                "INSERT INTO meta._marts_archive_log "
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


async def _log_archive_finish(
    run_id: uuid.UUID,
    *,
    status: str,
    cutoff: datetime | None = None,
    results: dict[str, dict[str, int]] | None = None,
    error: str | None = None,
) -> None:
    archived = (
        {t: r["archived"] for t, r in results.items()} if results is not None else None
    )
    pruned = (
        {t: r["pruned"] for t, r in results.items()} if results is not None else None
    )
    async with get_session() as db:
        await db.execute(
            text(
                "UPDATE meta._marts_archive_log "
                "SET status = :status, finished_at = :finished_at, cutoff = :cutoff, "
                "    archived = :archived, pruned = :pruned, error = :error "
                "WHERE id = :id"
            ),
            {
                "id": str(run_id),
                "status": status,
                "finished_at": datetime.now(UTC),
                "cutoff": cutoff,
                "archived": json.dumps(archived) if archived is not None else None,
                "pruned": json.dumps(pruned) if pruned is not None else None,
                "error": error,
            },
        )
        await db.commit()


@celery_app.task(name="app.tasks.marts_archive_tasks.archive_and_prune_marts_task")
def archive_and_prune_marts_task(
    days: int | None = None, triggered_by: str = "schedule"
) -> dict[str, object]:
    """Archives `raw_marts.*` rows older than `days` (`Settings.
    marts_local_retention_days` if omitted) to the second database, then
    prunes them from the primary. No-ops cleanly (real `{}` result,
    `status="skipped"`) if `RAW_MARTS_DATABASE_URL` isn't configured --
    same convention `export_and_prune_and_vacuum_task` follows for other
    optional infra.
    """
    configure_logging()
    from app.core.config import get_settings
    from app.retention.marts_archive import archive_and_prune_marts

    settings = get_settings()
    if not settings.raw_marts_archive_configured:
        log.info("marts_archive_tasks.skipped_not_configured")
        return {"status": "skipped", "reason": "RAW_MARTS_DATABASE_URL not configured"}

    run_id = run_async(_log_archive_start(trigger="scheduled", triggered_by=triggered_by))
    log.info("marts_archive_tasks.started", run_id=str(run_id), days=days)
    try:
        results, cutoff = run_async(archive_and_prune_marts(days))
    except Exception as exc:
        log.error("marts_archive_tasks.failed", run_id=str(run_id), error=str(exc))
        run_async(_log_archive_finish(run_id, status="failed", error=str(exc)[:2000]))
        raise
    log.info("marts_archive_tasks.finished", run_id=str(run_id), results=results)

    total_pruned = sum(counts["pruned"] for counts in results.values())
    if total_pruned > 0:
        from app.retention.vacuum import vacuum_analyze_marts_tables

        try:
            run_async(vacuum_analyze_marts_tables())
        except Exception as exc:
            log.error("marts_archive_tasks.vacuum_failed", run_id=str(run_id), error=str(exc))
            run_async(
                _log_archive_finish(
                    run_id, status="failed", cutoff=cutoff, results=results, error=str(exc)[:2000]
                )
            )
            raise

    run_async(
        _log_archive_finish(run_id, status="success", cutoff=cutoff, results=results)
    )
    return {"cutoff": cutoff.isoformat(), "results": results}
