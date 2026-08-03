"""`GET /v1/healthz` · `GET /v1/readyz` (`README.md` § API reference)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db, get_model_registry, get_redis_client
from app.schemas.health import (
    HealthResponse,
    ReadyComponent,
    ReadyResponse,
)
from app.service.ml.registry import ModelRegistry

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse()


@router.get("/readyz", response_model=ReadyResponse)
async def readyz(
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    registry: ModelRegistry = Depends(get_model_registry),
) -> ReadyResponse:
    try:
        await db.execute(text("SELECT 1"))
        database = ReadyComponent(ok=True)
    except Exception as exc:
        database = ReadyComponent(ok=False, detail=str(exc))

    try:
        await redis.ping()
        redis_component = ReadyComponent(ok=True)
    except Exception as exc:
        redis_component = ReadyComponent(ok=False, detail=str(exc))

    model_loaded = registry.bundle is not None
    model_component = ReadyComponent(
        ok=model_loaded,
        detail=None if model_loaded else "no Production model version loaded yet",
    )

    ready = database.ok and redis_component.ok and model_component.ok
    if not ready:
        response.status_code = 503
    return ReadyResponse(
        ready=ready, database=database, redis=redis_component, model=model_component
    )
