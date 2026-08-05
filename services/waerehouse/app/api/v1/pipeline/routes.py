"""Internal REST endpoints for downstream services to query pipeline
health and current storage utilization (README Phase 5).

Open -- no auth required for now, matching every other route in this
project's sibling services' current state.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.retention.size_monitor import check_database_size
from app.schemas.pipeline import StorageUtilization, SyncActivity

router = APIRouter(prefix="/v1/pipeline", tags=["pipeline"])

_DEFAULT_WINDOW_HOURS = 24


@router.get("/status", response_model=SyncActivity)
async def sync_activity(
    db: AsyncSession = Depends(get_db), window_hours: int = _DEFAULT_WINDOW_HOURS
) -> SyncActivity:
    """`meta._ingest_log` status counts over the lookback window -- a
    `staged` row this old is a real signal the consumer is stuck/behind,
    not just noise (a healthy consumer closes `staged` out to `success`/
    `sync_failed` within seconds of a landed event, not hours)."""
    result = await db.execute(
        text(
            "SELECT status, count(*) FROM meta._ingest_log "
            "WHERE started_at > now() - make_interval(hours => :window_hours) "
            "AND status IN ('success', 'sync_failed', 'staged') "
            "GROUP BY status"
        ),
        {"window_hours": window_hours},
    )
    counts = {row[0]: row[1] for row in result.all()}
    return SyncActivity(
        window_hours=window_hours,
        success=counts.get("success", 0),
        sync_failed=counts.get("sync_failed", 0),
        staged=counts.get("staged", 0),
    )


@router.get("/storage", response_model=StorageUtilization)
async def storage_utilization() -> StorageUtilization:
    report = await check_database_size()
    return StorageUtilization(
        size_bytes=report.size_bytes,
        limit_bytes=report.limit_bytes,
        pct_used=report.pct_used,
        severity=report.severity,
    )
