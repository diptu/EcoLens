"""Liveness/readiness/metrics endpoints.

`/v1/healthz` never touches a dependency — it just proves the process can
respond. `/v1/readyz` checks the things this service actually needs:
Postgres, Redis, and MLflow reachability (the fuller MLflow check —
latest run, Production version — lands with ECO-D43's
`mlops.health.run_health_check()`; this only pings the tracking server).
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_db, get_redis_client
from app.schemas.health import ComponentHealth, HealthResponse, ReadyResponse
from app.core.config import Settings
from app.core.metrics import metrics_as_text

router = APIRouter(tags=["health"])


@router.get("/v1/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse()


@router.get("/v1/readyz", response_model=ReadyResponse)
async def readyz(
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> ReadyResponse:
    components = [
        await _check_postgres(db),
        await _check_redis(redis),
        await _check_mlflow(settings),
    ]
    ready = all(component.healthy for component in components)
    response.status_code = 200 if ready else 503
    return ReadyResponse(
        status="ready" if ready else "not_ready", components=components
    )


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=metrics_as_text(), media_type="text/plain; version=0.0.4")


async def _check_postgres(db: AsyncSession) -> ComponentHealth:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        return ComponentHealth(name="postgres", healthy=False, detail=str(exc))
    return ComponentHealth(name="postgres", healthy=True)


async def _check_redis(redis: Redis) -> ComponentHealth:
    try:
        await redis.ping()
    except Exception as exc:
        return ComponentHealth(name="redis", healthy=False, detail=str(exc))
    return ComponentHealth(name="redis", healthy=True)


async def _check_mlflow(settings: Settings) -> ComponentHealth:
    url = f"{settings.mlflow_tracking_uri.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(url)
    except Exception as exc:
        return ComponentHealth(name="mlflow", healthy=False, detail=str(exc))
    healthy = resp.status_code == 200
    detail = None if healthy else f"unexpected status {resp.status_code}"
    return ComponentHealth(name="mlflow", healthy=healthy, detail=detail)
