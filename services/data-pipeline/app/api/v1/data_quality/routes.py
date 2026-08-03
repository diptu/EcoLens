"""`GET /v1/data-quality/{summary,issues,outliers,schema}` and
`POST /v1/data-quality/recheck/{source}` (API_SPECEFICATIONS.md §3.1-3.5).

All the signal-mapping/query/cache logic lives in `app.service.dataquality` — see its module docstring for what "data quality tests" maps
onto in this codebase. This router is just query-param/header plumbing
and the role gate, same split as `api/routers/datasources.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db, get_redis_client
from app.schemas.data_quality import (
    DataQualityIssuesResponse,
    DataQualityOutliersResponse,
    DataQualitySchemaResponse,
    DataQualitySummaryResponse,
    IssueCategory,
    IssueStatus,
    PublicDataQualitySummaryResponse,
    RecheckRequest,
    RecheckResponse,
    Severity,
)
from app.core.security import ROLES, Principal, require_roles
from app.service.dataquality import (
    _parse_window_to_minutes,
    get_public_summary,
    get_schema_report,
    get_summary,
    list_issues,
    list_outliers,
    run_recheck_in_background,
    trigger_recheck,
)
from app.models.datasources import CATALOG_BY_ID
from app.service.datasources.service import require_catalog_entry

router = APIRouter(prefix="/v1/data-quality", tags=["data-quality"])


@router.get("/summary", response_model=DataQualitySummaryResponse)
async def get_summary_endpoint(
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> DataQualitySummaryResponse:
    return await get_summary(db, redis)


@router.get("/summary/public", response_model=PublicDataQualitySummaryResponse)
async def get_public_summary_endpoint(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> PublicDataQualitySummaryResponse:
    """No `require_roles` gate, unlike every other route in this file --
    deliberately. See `PublicDataQualitySummaryResponse`'s docstring:
    this exposes only two aggregate numbers (no source IDs/descriptions),
    specifically so a browser client (the dashboard) can call it without
    holding this service's own bearer token, which is a separate auth
    domain from the IAM session token the dashboard already has (see
    `core/security.py`'s module docstring)."""
    return await get_public_summary(db, redis)


@router.get("/issues", response_model=DataQualityIssuesResponse)
async def list_issues_endpoint(
    source_id: str | None = None,
    severity: Severity | None = None,
    category: IssueCategory | None = None,
    status: IssueStatus = "open",
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> DataQualityIssuesResponse:
    if source_id is not None:
        require_catalog_entry(source_id)
    return await list_issues(
        db,
        redis,
        source_id=source_id,
        severity=severity,
        category=category,
        status=status,
        limit=limit,
        cursor=cursor,
    )


@router.get("/outliers", response_model=DataQualityOutliersResponse)
async def list_outliers_endpoint(
    source_id: str | None = None,
    metric: str | None = None,
    z_score_min: float = Query(default=3.0, ge=0),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> DataQualityOutliersResponse:
    if source_id is not None:
        require_catalog_entry(source_id)
    now = datetime.now(UTC)
    return await list_outliers(
        db,
        redis,
        source_id=source_id,
        metric=metric,
        z_score_min=z_score_min,
        from_=from_ or now - timedelta(days=7),
        to=to or now,
        limit=limit,
    )


@router.get("/schema", response_model=DataQualitySchemaResponse)
async def get_schema_report_endpoint(
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> DataQualitySchemaResponse:
    return await get_schema_report(db, redis)


@router.post("/recheck/{source}", response_model=RecheckResponse, status_code=202)
async def trigger_recheck_endpoint(
    source: str,
    background_tasks: BackgroundTasks,
    body: RecheckRequest = RecheckRequest(),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles("admin")),
    redis: Redis = Depends(get_redis_client),
) -> RecheckResponse:
    response = await trigger_recheck(
        redis,
        source,
        body.tests,
        body.window,
        idempotency_key=idempotency_key,
        triggered_by=principal.sub,
    )
    entry = CATALOG_BY_ID[source]
    lookback_minutes = _parse_window_to_minutes(body.window)
    background_tasks.add_task(
        run_recheck_in_background,
        redis,
        source,
        entry.registry_key,
        lookback_minutes,
        principal.sub,
    )
    return response
