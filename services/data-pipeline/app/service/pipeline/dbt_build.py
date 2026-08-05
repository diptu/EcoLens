"""Global-locked `dbt build` runner.

Shared by three real triggers that all need to run a *full* `dbt build`
outside a training/schedule context:
  - `datasources.actions.run_backfill_in_background` -- one build after an
    API-triggered backfill's raw rows land (TODO.md's "backfill" section:
    the CLI (`scripts/backfill.py`) already did this; the dashboard-facing
    API path didn't).
  - `pipelines.trigger_dbt_warehouse_build` -- the dashboard's manual
    "Run now" on the `pipe-dbt-warehouse` row.
  - `dbt_build_watch.watch_and_build` -- the periodic background rebuild
    (`main.py`'s lifespan) that keeps `raw_marts.*` from drifting out of
    sync with continuous ingestion in between the two triggers above,
    which only ever fire on a backfill or a manual click.

All three call sites share one lock (`DBT_BUILD_LOCK_KEY`), not a
per-caller one: two `dbt build` invocations sharing the same
`--project-dir` (same `target/` dir, same mart tables) can race
destructively, so only one may run at a time regardless of who
triggered it.
"""

from __future__ import annotations

import asyncio
import uuid

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.service.dbt_runner import run_dbt
from app.service.pipeline.dbt_build_log import log_dbt_build_finish, log_dbt_build_start

log = get_logger(__name__)

DBT_BUILD_LOCK_KEY = "dbt:build:lock"
DBT_BUILD_LOCK_TTL_SECONDS = 1800
DBT_BUILD_LOCK_POLL_SECONDS = 2
DBT_BUILD_LOCK_WAIT_SECONDS = 1800


class DbtBuildLockTimeout(Exception):
    """Raised when a `dbt build` couldn't acquire the global lock within
    `DBT_BUILD_LOCK_WAIT_SECONDS` -- another build was still holding it the
    whole time. Callers decide whether that's fatal for them."""


async def run_dbt_build_locked(
    redis: Redis,
    *,
    trigger: str,
    triggered_by: str,
    max_wait_seconds: int = DBT_BUILD_LOCK_WAIT_SECONDS,
) -> int:
    """Runs one `dbt build`, holding a global lock so it never overlaps
    another concurrent build (from either call site above). Returns the
    real dbt exit code. Raises `DbtBuildLockTimeout` if the lock couldn't
    be acquired within `max_wait_seconds` -- never swallows that silently.
    A lock-timeout writes no `meta._dbt_build_log` row -- `run_dbt` was
    never actually invoked, so there's no build attempt to log (see
    `dbt_build_log.py`).

    `max_wait_seconds=0` (the manual dashboard trigger's use -- see
    `pipelines.trigger_dbt_warehouse_build`) tries exactly once and fails
    fast rather than holding an HTTP request open for however long another
    build takes; the background auto-trigger uses the long default since
    nothing user-facing is waiting on it.

    `trigger` is the coarse call-site category written to `meta.
    _dbt_build_log.trigger` (`"backfill_auto"` / `"dashboard_manual"` --
    see that module's docstring); `triggered_by` is the free-form
    identifier each caller already threads through.
    """
    lock_token = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max_wait_seconds
    while True:
        acquired = bool(
            await redis.set(
                DBT_BUILD_LOCK_KEY, lock_token, ex=DBT_BUILD_LOCK_TTL_SECONDS, nx=True
            )
        )
        if acquired or loop.time() >= deadline:
            break
        await asyncio.sleep(DBT_BUILD_LOCK_POLL_SECONDS)

    if not acquired:
        log.error(
            "dbt_build.lock_timeout",
            triggered_by=triggered_by,
            waited_seconds=max_wait_seconds,
        )
        raise DbtBuildLockTimeout(
            f"Could not acquire '{DBT_BUILD_LOCK_KEY}' within "
            f"{max_wait_seconds}s -- another build is still running"
        )

    try:
        settings = get_settings()
        build_log_id = await log_dbt_build_start(
            subcommand="build",
            target=settings.dbt_target,
            trigger=trigger,
            triggered_by=triggered_by,
        )
        try:
            exit_code = await asyncio.to_thread(
                run_dbt, "build", settings.dbt_project_dir, settings.dbt_target
            )
        except Exception as exc:
            # `run_dbt` itself never raises (see its own docstring) -- this
            # only catches something going wrong in the `asyncio.to_thread`
            # plumbing itself, but either way the 'running' row must still
            # be closed out, not left dangling forever.
            await log_dbt_build_finish(build_log_id, status="failed", error=str(exc))
            raise
        if exit_code != 0:
            log.error(
                "dbt_build.failed", triggered_by=triggered_by, exit_code=exit_code
            )
            await log_dbt_build_finish(
                build_log_id,
                status="failed",
                exit_code=exit_code,
                error=f"dbt build exited {exit_code}",
            )
        else:
            log.info("dbt_build.succeeded", triggered_by=triggered_by)
            await log_dbt_build_finish(
                build_log_id, status="success", exit_code=exit_code
            )
        return exit_code
    finally:
        # Only clear the lock if we're still the ones holding it -- a lease
        # that outlived `DBT_BUILD_LOCK_TTL_SECONDS` may already have been
        # reclaimed by another waiter, and a plain DEL here could release a
        # different build's lock out from under it.
        current = await redis.get(DBT_BUILD_LOCK_KEY)
        current_value = current.decode() if isinstance(current, bytes) else current
        if current_value == lock_token:
            await redis.delete(DBT_BUILD_LOCK_KEY)
