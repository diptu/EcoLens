"""`GET/POST /v1/ingestion/*` (API_SPECEFICATIONS.md §2.1-2.8).

All the reframing/query/cache logic lives in `app.service.pipelines` —
see its module docstring and `app.models.pipelines`'s for what this
maps onto in a codebase with 6 real pipelines, not the spec's fictional 8.
This router is just query-param/header plumbing and the role gate, same
split as `api/routers/datasources.py`/`data_quality.py`.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_db, get_redis_client
from app.schemas.pipelines import (
    FailedRunsResponse,
    PauseRequest,
    PauseResponse,
    PipelinesListResponse,
    PublicRunsListResponse,
    ResumeResponse,
    RetryQueueResponse,
    RunDetail,
    RunsListResponse,
    SchedulerResponse,
)
from app.core.security import ROLES, Principal, require_roles
from app.core.config import Settings
from app.service import pipelines as service

router = APIRouter(prefix="/v1/ingestion", tags=["ingestion"])


@router.get("/pipelines", response_model=PipelinesListResponse)
async def list_pipelines_endpoint(
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> PipelinesListResponse:
    return await service.list_pipelines(db, redis, settings)


@router.get("/public/pipelines", response_model=PipelinesListResponse)
async def list_pipelines_public_endpoint(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> PipelinesListResponse:
    """No `require_roles` gate, unlike `list_pipelines_endpoint` above --
    deliberately. Pipeline names/schedules/aggregate 24h stats aren't
    sensitive, and the dashboard has no way to hold a bearer token for
    this service's own separate auth domain (`core/security.py`) -- same
    reasoning as `data_quality`'s `GET /summary/public`. Same response
    shape as the authenticated route, same cache -- this is a real
    public projection, not a stripped-down summary (unlike data-quality's
    public endpoint, there's nothing here worth narrowing)."""
    return await service.list_pipelines(db, redis, settings)


@router.get("/runs", response_model=RunsListResponse)
async def list_runs_endpoint(
    pipeline_id: str | None = None,
    source_id: str | None = None,
    status: str | None = None,
    trigger: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> RunsListResponse:
    return await service.list_runs(
        db,
        redis,
        pipeline_id=pipeline_id,
        source_id=source_id,
        status=status,
        trigger=trigger,
        from_=from_,
        to=to,
        limit=limit,
        cursor=cursor,
    )


@router.get("/public/runs", response_model=PublicRunsListResponse)
async def list_runs_public_endpoint(
    pipeline_id: str | None = None,
    source_id: str | None = None,
    status: str | None = None,
    trigger: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> PublicRunsListResponse:
    """No `require_roles` gate, unlike `list_runs_endpoint` above --
    same reasoning as `list_pipelines_public_endpoint`. Unlike that one,
    this *is* narrowed: see `PublicRunOut`'s docstring for what's
    dropped and why."""
    return await service.list_runs_public(
        db,
        redis,
        pipeline_id=pipeline_id,
        source_id=source_id,
        status=status,
        trigger=trigger,
        from_=from_,
        to=to,
        limit=limit,
        cursor=cursor,
    )


@router.get("/runs/{id}", response_model=RunDetail)
async def get_run_endpoint(
    id: str,
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
) -> RunDetail:
    return await service.get_run(db, id)


@router.get("/failed", response_model=FailedRunsResponse)
async def list_failed_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
) -> FailedRunsResponse:
    return await service.list_failed(db, limit=limit, cursor=cursor)


@router.get("/public/failed", response_model=FailedRunsResponse)
async def list_failed_public_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> FailedRunsResponse:
    """No `require_roles` gate, unlike `list_failed_endpoint` above --
    same reasoning as `list_pipelines_public_endpoint`, plus
    `error.message` redaction (see `service.pipelines`'s
    `list_failed_public` / `_redact_public_error_message`)."""
    return await service.list_failed_public(db, limit=limit, cursor=cursor)


@router.get("/retry-queue")
async def list_retry_queue_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_retry_queue(db, limit=limit)


@router.get("/public/retry-queue", response_model=RetryQueueResponse)
async def list_retry_queue_public_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> RetryQueueResponse:
    """No `require_roles` gate -- same reasoning as
    `list_failed_public_endpoint`, including the `last_error.message`
    redaction."""
    return await service.list_retry_queue_public(db, limit=limit)


@router.get("/scheduler", response_model=SchedulerResponse)
async def get_scheduler_endpoint(
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> SchedulerResponse:
    return await service.get_scheduler_status(db, redis)


@router.get("/public/scheduler", response_model=SchedulerResponse)
async def get_scheduler_public_endpoint(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> SchedulerResponse:
    """No `require_roles` gate -- same reasoning as
    `list_pipelines_public_endpoint`. Nothing here needs narrowing:
    `SchedulerStatus`'s own docstring already documents that
    `prefect_version`/`prefect_api_url` are always `None` and there's no
    per-source hostname/credential detail anywhere in this response."""
    return await service.get_scheduler_status(db, redis)


@router.post("/{id}/pause", response_model=PauseResponse)
async def pause_pipeline_endpoint(
    id: str,
    body: PauseRequest = PauseRequest(),
    principal: Principal = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> PauseResponse:
    return await service.pause_pipeline(db, redis, id, body.reason, principal.sub)


@router.post("/{id}/resume", response_model=ResumeResponse)
async def resume_pipeline_endpoint(
    id: str,
    principal: Principal = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> ResumeResponse:
    return await service.resume_pipeline(db, redis, id, principal.sub)
