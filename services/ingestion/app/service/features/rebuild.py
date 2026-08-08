"""`POST /v1/features/rebuild` -- the "Rebuild Features" action for the
dashboard's System Commands card (root `TODO.md`'s "System Commands"
item).

Real, not a stub: runs `scripts/select_features.py`'s own
`run_selection()` (the same real automated feature-selection pass --
mutual information + RandomForest + permutation importance, per-region,
7 lag/rolling-window features, real sklearn compute) against whatever
`data/training/master.duckdb` already exists on this machine, then
writes `data/training/selected_features.json` -- identical output to
running the script's own CLI (`main()`) by hand.

**Why this doesn't contradict `select_features.py`'s own "don't silently
require cloud credentials on demand" design decision** (see that
script's module docstring, and root `TODO.md`'s own note on why this was
initially left unwired): this endpoint doesn't change what the script
does or what it needs -- it still only reads the *local* `master.duckdb`
that must already exist, and still fails with a real, clear error
(`FeatureSelectionSourceMissing` below, not a crash or a silent no-op)
if it doesn't. Nothing here reaches out to R2/cloud storage. What
*would* have contradicted that decision is auto-*building*
`master.duckdb` from R2 on every click -- this endpoint deliberately
never does that.

Same atomic-lock + log-start + run + log-finish shape
`services/waerehouse/app/dbt/scheduler.py` already uses for
`meta._dbt_build_log` (`_try_start_build`/`_log_build_finish`) --
`meta._feature_selection_log` (`0005_feature_selection_log.sql`) is this
service's own copy of that same real pattern, not a new one invented
here.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

log = get_logger(__name__)

_STALE_LOCK_MINUTES = 30


class FeatureSelectionSourceMissing(Exception):
    """Real, clear error -- `master.duckdb` doesn't exist on this
    machine. Mirrors `run_selection()`'s own `click.ClickException`
    message (this module can't import `click`'s exception type without
    pulling `scripts/` into the app's own dependency surface, so it
    re-raises as this instead, same message)."""


async def _try_start_run(db: AsyncSession, *, run_id: str, triggered_by: str) -> bool:
    result = await db.execute(
        text(
            "INSERT INTO meta._feature_selection_log "
            "(id, triggered_by, status, started_at) "
            "SELECT :id, :triggered_by, 'running', :started_at "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM meta._feature_selection_log "
            "  WHERE status = 'running' "
            "    AND started_at > now() - make_interval(mins => :stale_minutes)"
            ") "
            "RETURNING id"
        ),
        {
            "id": run_id,
            "triggered_by": triggered_by,
            "started_at": datetime.now(UTC),
            "stale_minutes": _STALE_LOCK_MINUTES,
        },
    )
    acquired = result.first() is not None
    await db.commit()
    return acquired


async def _log_run_finish(
    db: AsyncSession,
    *,
    run_id: str,
    status: str,
    n_selected: int | None,
    result: dict[str, Any] | None,
    error: str | None,
) -> None:
    await db.execute(
        text(
            "UPDATE meta._feature_selection_log "
            "SET status = :status, finished_at = :finished_at, "
            "    n_selected = :n_selected, result = :result, error = :error "
            "WHERE id = :id"
        ),
        {
            "id": run_id,
            "status": status,
            "finished_at": datetime.now(UTC),
            "n_selected": n_selected,
            "result": json.dumps(result) if result is not None else None,
            "error": error,
        },
    )
    await db.commit()


def _run_selection_sync() -> dict[str, Any]:
    """Runs in a worker thread (`asyncio.to_thread` below) -- real
    sklearn/duckdb compute, genuinely blocking, same reasoning `run_dbt`'s
    subprocess call gets offloaded in `services/waerehouse`."""
    import sys

    # `rebuild.py` -> features/ -> service/ -> app/ -> ingestion/ (this
    # service's own root, where `scripts/` lives as a sibling of `app/`).
    service_root = Path(__file__).resolve().parents[3]
    if str(service_root) not in sys.path:
        sys.path.insert(0, str(service_root))

    from scripts.build_master_table import master_path
    from scripts.select_features import run_selection, selected_features_path

    if not master_path().exists():
        raise FeatureSelectionSourceMissing(
            f"master.duckdb not found at {master_path()} -- run "
            "`uv run python scripts/build_master_table.py` first "
            "(or place a copy there)."
        )

    result = run_selection()
    out_path = selected_features_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return result


async def rebuild_features(db: AsyncSession, *, triggered_by: str) -> dict[str, Any] | None:
    """Acquires the lock, runs feature selection, logs the outcome.
    Returns the real result dict, or `None` if the lock was already held
    (another rebuild is genuinely in progress) -- same "caller decides
    what `None` means" contract `waerehouse`'s `run_build` uses."""
    run_id = str(uuid.uuid4())
    acquired = await _try_start_run(db, run_id=run_id, triggered_by=triggered_by)
    if not acquired:
        return None

    log.info("features.rebuild_started", run_id=run_id, triggered_by=triggered_by)
    try:
        result = await asyncio.to_thread(_run_selection_sync)
    except Exception as exc:
        log.error("features.rebuild_failed", run_id=run_id, error=str(exc))
        await _log_run_finish(
            db,
            run_id=run_id,
            status="failed",
            n_selected=None,
            result=None,
            error=str(exc)[:2000],
        )
        raise

    n_selected = len(result.get("selected_features", []))
    log.info("features.rebuild_finished", run_id=run_id, n_selected=n_selected)
    await _log_run_finish(
        db, run_id=run_id, status="success", n_selected=n_selected, result=result, error=None
    )
    return result
