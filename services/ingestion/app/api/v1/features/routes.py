"""`POST /v1/features/rebuild` -- the "Rebuild Features" action for the
dashboard's System Commands card (root `TODO.md`'s "System Commands"
item). See `app.service.features.rebuild`'s own module docstring for
why this is real and doesn't contradict `select_features.py`'s existing
"don't silently require cloud credentials on demand" design.

Synchronous from the HTTP caller's point of view (like `POST /v1/dbt/
build`) -- real sklearn/duckdb compute, genuinely offloaded to a thread
(`rebuild_features`'s own docstring), but the request just waits for it;
no separate poll-for-completion needed the way a multi-day backfill
does. `GET /v1/features/rebuild/runs` is the history list, same
"open, no auth -- read access to run history isn't the privileged part"
reasoning `GET /v1/dbt/build/runs` uses.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import ApiError
from app.schemas.features import (
    FeatureRebuildRunOut,
    FeatureRebuildRunsListResponse,
    FeatureRebuildTriggerResponse,
)
from app.service.features.rebuild import FeatureSelectionSourceMissing, rebuild_features

router = APIRouter(prefix="/v1/features", tags=["features"])


@router.post("/rebuild", response_model=FeatureRebuildTriggerResponse)
async def trigger_feature_rebuild(
    db: AsyncSession = Depends(get_db),
) -> FeatureRebuildTriggerResponse:
    try:
        result = await rebuild_features(db, triggered_by="dashboard")
    except FeatureSelectionSourceMissing as exc:
        raise ApiError(422, "master_duckdb_missing", str(exc)) from exc

    if result is None:
        raise ApiError(
            409,
            "rebuild_in_progress",
            "Another feature-selection rebuild is already running -- wait for it to finish.",
        )

    rows = await db.execute(
        text(
            "SELECT id FROM meta._feature_selection_log "
            "WHERE status = 'success' ORDER BY finished_at DESC LIMIT 1"
        )
    )
    run_id = str(rows.scalar_one())
    return FeatureRebuildTriggerResponse(
        run_id=run_id, status="success", n_selected=len(result["selected_features"])
    )


@router.get("/rebuild/runs", response_model=FeatureRebuildRunsListResponse)
async def list_feature_rebuild_runs(
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> FeatureRebuildRunsListResponse:
    result = await db.execute(
        text(
            "SELECT id, triggered_by, status, started_at, finished_at, "
            "n_selected, result, error "
            "FROM meta._feature_selection_log ORDER BY started_at DESC LIMIT :limit"
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()
    return FeatureRebuildRunsListResponse(
        data=[FeatureRebuildRunOut(**{**dict(r), "id": str(r["id"])}) for r in rows]
    )
