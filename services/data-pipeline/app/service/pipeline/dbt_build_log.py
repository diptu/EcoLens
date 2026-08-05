"""`meta._dbt_build_log` read/write (`migrations/0023_dbt_build_log.sql`)
-- TODO.md's backfill-section "Follow-up" item: a persisted, queryable
history of dbt build outcomes, mirroring `training_worker._log_training_
start`/`_log_training_finish`'s pattern for `meta._training_log`.

**Honest current coverage** -- not literally every `run_dbt` caller in
this codebase writes here yet:
  - `run_dbt_build_locked` (`dbt_build.py`) -- covers the backfill
    auto-trigger (`trigger="backfill_auto"`), the dashboard's manual
    "Run now" (`trigger="dashboard_manual"`), and the periodic background
    rebuild (`trigger="periodic_watch"`, `dbt_build_watch.py` -- the fix
    for `raw_marts.*` drifting out of sync with continuous ingestion
    between backfills/manual triggers), since all three go through this
    one shared, locked function.
  - `POST /v1/dbt/{subcommand}` (`api/v1/dbt/routes.py`) -- the general-
    purpose admin endpoint, logged directly there since it doesn't take
    the global build lock (`trigger="admin_api"`).

Still not logged: the Prefect `dbt-build` task (`pipeline.flows`) and the
`ecolens-pipeline dbt {build,run,test}` CLI commands (`app/cli.py`) --
both call `dbt_runner.run_dbt` directly, outside an HTTP request/response
cycle where threading an async DB write through cleanly needs more than
this pass's scope. Tracked, not silently claimed as done.

**Logging here is best-effort, never load-bearing**: both functions
below catch and log their own DB errors rather than raising. This table
is pure observability bolted onto an already-working build path -- a
migration that hasn't run yet, a transient DB hiccup, or any other
logging failure must never prevent (or crash the caller of) an actual
`dbt build`, the same way a broken `meta._training_log` insert shouldn't
be allowed to stop a real training run.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_session
from app.schemas.dbt import DbtBuildRunOut

logger = get_logger(__name__)


async def log_dbt_build_start(
    *, subcommand: str, target: str, trigger: str, triggered_by: str
) -> uuid.UUID | None:
    """Insert a `'running'` row. Returns the row id to close out later, or
    `None` if the insert itself failed (logged, not raised -- see module
    docstring); `log_dbt_build_finish` treats `None` as a no-op."""
    log_id = uuid.uuid4()
    try:
        async with get_session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO meta._dbt_build_log
                        (id, subcommand, target, trigger, triggered_by, status, started_at)
                    VALUES
                        (:id, :subcommand, :target, :trigger, :triggered_by, 'running', now())
                    """
                ),
                {
                    "id": str(log_id),
                    "subcommand": subcommand,
                    "target": target,
                    "trigger": trigger,
                    "triggered_by": triggered_by,
                },
            )
    except Exception as exc:
        logger.error(
            "dbt_build_log.start_failed", triggered_by=triggered_by, error=str(exc)
        )
        return None
    return log_id


async def log_dbt_build_finish(
    log_id: uuid.UUID | None,
    *,
    status: str,
    exit_code: int | None = None,
    error: str | None = None,
) -> None:
    """Close out a row as `'success'`/`'failed'`. A no-op if `log_id` is
    `None` (the start insert already failed and logged why)."""
    if log_id is None:
        return
    try:
        async with get_session() as session:
            await session.execute(
                text(
                    """
                    UPDATE meta._dbt_build_log
                    SET finished_at = now(),
                        status = :status,
                        exit_code = :exit_code,
                        error = :error
                    WHERE id = :id
                    """
                ),
                {
                    "id": str(log_id),
                    "status": status,
                    "exit_code": exit_code,
                    "error": error[:500] if error else None,
                },
            )
    except Exception as exc:
        logger.error("dbt_build_log.finish_failed", log_id=str(log_id), error=str(exc))


async def list_dbt_build_runs(
    db: AsyncSession, limit: int = 20
) -> list[DbtBuildRunOut]:
    """Real `meta._dbt_build_log` history, newest first -- backs
    `GET /v1/dbt/runs`. A `status == "running"` row is the real
    "is a build in flight right now" signal, distinct from (and a real
    persisted alternative to) the transient `dbt:build:lock` Redis key
    `run_dbt_build_locked` also holds for the same duration."""
    result = await db.execute(
        text(
            "SELECT id, subcommand, target, trigger, triggered_by, status, "
            "started_at, finished_at, exit_code, error "
            "FROM meta._dbt_build_log ORDER BY started_at DESC LIMIT :limit"
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()
    return [
        DbtBuildRunOut(
            id=str(row["id"]),
            subcommand=row["subcommand"],
            target=row["target"],
            trigger=row["trigger"],
            triggered_by=row["triggered_by"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            exit_code=row["exit_code"],
            error=row["error"],
        )
        for row in rows
    ]
