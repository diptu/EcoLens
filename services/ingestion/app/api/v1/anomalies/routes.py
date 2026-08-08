"""`GET /v1/anomalies` / `GET /v1/anomalies/summary` /
`PATCH /v1/anomalies/{id}` -- real `meta.anomalies` listing + status
workflow, backing the dashboard's anomaly-detection page (root
TODO.md's "make every page fully functional with real data"). See
`app.service.anomalies`'s own module docstring for the real severity/
method derivation.

Open, no auth -- same reasoning `GET /v1/data-quality/summary/public`
already documents: read access to anomaly detail isn't the privileged
part on this platform, and the mutation (status only, an operator
workflow annotation) doesn't touch or re-score any underlying data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import ApiError
from app.schemas.anomalies import (
    AnomalyListResponse,
    AnomalyOut,
    AnomalySummaryResponse,
    UpdateAnomalyStatusRequest,
)
from app.service.anomalies import get_anomaly_summary, list_anomalies, update_anomaly_status

router = APIRouter(prefix="/v1/anomalies", tags=["anomalies"])


@router.get("", response_model=AnomalyListResponse)
async def list_anomalies_endpoint(
    severity: str | None = Query(default=None),
    method: str | None = Query(default=None),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    reason_kind: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> AnomalyListResponse:
    rows, total = await list_anomalies(
        db,
        severity=severity,
        method=method,
        status=status,
        source=source,
        reason_kind=reason_kind,
        search=search,
        limit=limit,
        offset=offset,
    )
    return AnomalyListResponse(
        meta={"total": total, "limit": limit, "offset": offset},
        data=[AnomalyOut(**r) for r in rows],
    )


@router.get("/summary", response_model=AnomalySummaryResponse)
async def get_anomaly_summary_endpoint(
    db: AsyncSession = Depends(get_db),
) -> AnomalySummaryResponse:
    return AnomalySummaryResponse(**(await get_anomaly_summary(db)))


@router.patch("/{anomaly_id}", response_model=AnomalyOut)
async def update_anomaly_status_endpoint(
    anomaly_id: str,
    body: UpdateAnomalyStatusRequest,
    db: AsyncSession = Depends(get_db),
) -> AnomalyOut:
    updated = await update_anomaly_status(db, anomaly_id, body.status)
    if updated is None:
        raise ApiError(404, "anomaly_not_found", f"No anomaly with id '{anomaly_id}'.")
    return AnomalyOut(**updated)
