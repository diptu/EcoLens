"""`GET /v1/data-sources[/{id}]`, `PATCH /v1/data-sources/{id}`,
`POST /v1/data-sources/{id}/run`, `POST /v1/data-sources/{id}/backfill`,
`GET /v1/data-sources/{id}/health`, `GET /v1/data-sources/{id}/history`
(API_SPECEFICATIONS.md §1.1-1.6).

Lists/reads the data-source catalog (`app.models.datasources`)
merged with live health/run stats, lets an admin edit a source's
schedule/enabled flag/description/auth type/metadata, trigger an
immediate fetch or a date-range backfill, and inspect higher-resolution
health/run-history views — powers the dashboard's Data Sources admin
page. All the merge/filter/sort/pagination/cache/validation logic lives
in `app.service.datasources.service`/`actions`/`monitoring`; this router is
just query-param/header plumbing and the role gate (read/edit endpoints
only — `run`/`backfill` are deliberately open, no auth required, so any
dashboard visitor can trigger a pipeline).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_db, get_redis_client
from app.schemas.datasources import (
    BackfillRequest,
    BackfillTriggerResponse,
    Category,
    DataSourceOut,
    DataSourcesListResponse,
    HealthStatus,
    PatchDataSourceRequest,
    RunRequest,
    RunStatus,
    RunTriggerResponse,
    SourceHealthResponse,
    SourceHistoryResponse,
)
from app.core.security import ROLES, Principal, require_roles
from app.core.config import Settings
from app.service.datasources.actions import (
    run_backfill_in_background,
    run_in_background,
    trigger_backfill,
    trigger_run,
)
from app.models.datasources import CATALOG_BY_ID
from app.service.datasources.monitoring import get_source_health, get_source_history
from app.service.datasources.service import (
    ListDataSourcesQuery,
    get_data_source,
    list_data_sources,
    update_data_source,
)

router = APIRouter(prefix="/v1/data-sources", tags=["data-sources"])

SortField = Literal["name", "category", "last_run_at", "success_rate_pct"]
Order = Literal["asc", "desc"]


@router.get("", response_model=DataSourcesListResponse)
async def list_data_sources_endpoint(
    category: Category | None = None,
    enabled: bool | None = None,
    health: HealthStatus | None = None,
    search: str | None = Query(default=None, max_length=64),
    sort: SortField = "name",
    order: Order = "asc",
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    _principal=Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> DataSourcesListResponse:
    query = ListDataSourcesQuery(
        category=category,
        enabled=enabled,
        health=health,
        search=search,
        sort=sort,
        order=order,
        limit=limit,
        cursor=cursor,
    )
    return await list_data_sources(db, redis, settings, query)


@router.get("/{id}", response_model=DataSourceOut)
async def get_data_source_endpoint(
    id: str,
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> DataSourceOut:
    return await get_data_source(db, redis, settings, id)


@router.patch("/{id}", response_model=DataSourceOut)
async def patch_data_source_endpoint(
    id: str,
    body: PatchDataSourceRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> DataSourceOut:
    return await update_data_source(
        db, redis, settings, id, body, if_match, edited_by=principal.sub
    )


@router.post("/{id}/run", response_model=RunTriggerResponse, status_code=202)
async def trigger_run_endpoint(
    id: str,
    background_tasks: BackgroundTasks,
    body: RunRequest = RunRequest(),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    reason: str | None = Header(default=None, alias="X-Reason"),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> RunTriggerResponse:
    # Deliberately open — no role/auth gate. Triggering an ingestion run
    # is not a privileged action in this platform's current scope; see
    # `triggered_by="public"` below rather than a real principal's `sub`.
    response = await trigger_run(
        db,
        redis,
        id,
        body,
        idempotency_key=idempotency_key,
        reason=reason,
        triggered_by="public",
    )
    entry = CATALOG_BY_ID[id]
    background_tasks.add_task(
        run_in_background, entry.registry_key, body.force, "public"
    )
    return response


@router.post("/{id}/backfill", response_model=BackfillTriggerResponse, status_code=202)
async def trigger_backfill_endpoint(
    id: str,
    background_tasks: BackgroundTasks,
    body: BackfillRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    redis: Redis = Depends(get_redis_client),
) -> BackfillTriggerResponse:
    # Deliberately open — same reasoning as trigger_run_endpoint above.
    response = await trigger_backfill(
        redis, id, body, idempotency_key=idempotency_key, triggered_by="public"
    )
    entry = CATALOG_BY_ID[id]
    background_tasks.add_task(
        run_backfill_in_background, redis, id, entry.registry_key, body.start, body.end
    )
    return response


@router.get("/{id}/health", response_model=SourceHealthResponse)
async def get_source_health_endpoint(
    id: str,
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> SourceHealthResponse:
    return await get_source_health(db, redis, settings, id)


@router.get("/{id}/history", response_model=SourceHistoryResponse)
async def get_source_history_endpoint(
    id: str,
    status: RunStatus | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> SourceHistoryResponse:
    return await get_source_history(
        db, redis, id, status=status, from_=from_, to=to, limit=limit, cursor=cursor
    )
