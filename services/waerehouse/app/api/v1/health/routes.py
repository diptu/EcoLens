"""Liveness/readiness/metrics endpoints.

`/v1/healthz` never touches a dependency -- it just proves the process
can respond. `/v1/readyz` checks the two things this service actually
needs: Postgres (`raw.*` writes, `meta._ingest_log` close-out) and
RabbitMQ (consuming landed events) -- no Redis, unlike `services/
ingestion`'s equivalent route: this service has no circuit-breaker/
rate-limit state to keep, `app.core.config`'s own module docstring
covers the scoped-down dependency set.

`/metrics` renders `app.core.metrics.REGISTRY` -- the warehouse-domain
subset `consumers.landed_events`/`retention.*` actually populate.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.metrics import metrics_as_text
from app.db.rabbitmq import get_rabbitmq_connection
from app.schemas.health import ComponentHealth, HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/v1/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse()


@router.get("/v1/readyz", response_model=ReadyResponse)
async def readyz(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ReadyResponse:
    components = [
        await _check_postgres(db),
        await _check_rabbitmq(),
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


async def _check_rabbitmq() -> ComponentHealth:
    try:
        connection = await get_rabbitmq_connection()
        if connection.is_closed:
            return ComponentHealth(
                name="rabbitmq", healthy=False, detail="connection is closed"
            )
    except Exception as exc:
        return ComponentHealth(name="rabbitmq", healthy=False, detail=str(exc))
    return ComponentHealth(name="rabbitmq", healthy=True)
