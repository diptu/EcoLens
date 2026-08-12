"""`GET /v1/retention/runs` -- real `meta._retention_log` history for the
daily export-and-prune-and-vacuum Celery Beat job (`app.tasks.
retention_tasks`, root `TODO.md`'s "Vacuum Database"/"Scheduled
Operations" items). Read-only, no trigger endpoint here -- this job
runs on a real schedule (`app.celery_app.beat_schedule`), not on
demand; an operator with shell access already has `ecolens-warehouse
export-and-prune`/`vacuum` for a manual run. Same open-no-auth
reasoning `GET /v1/dbt/build/runs` already uses: read access to run
history isn't the privileged part.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_log_db
from app.schemas.retention import RetentionRunOut, RetentionRunsListResponse

router = APIRouter(prefix="/v1/retention", tags=["retention"])


@router.get("/runs", response_model=RetentionRunsListResponse)
async def list_retention_runs_endpoint(
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_log_db),
) -> RetentionRunsListResponse:
    result = await db.execute(
        text(
            "SELECT id, trigger, triggered_by, status, started_at, "
            "finished_at, pruned, vacuumed, error "
            "FROM meta._retention_log ORDER BY started_at DESC LIMIT :limit"
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()
    return RetentionRunsListResponse(
        data=[RetentionRunOut(**{**dict(r), "id": str(r["id"])}) for r in rows]
    )
