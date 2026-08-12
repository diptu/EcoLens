"""Liveness/readiness/metrics endpoints.

`/v1/healthz` never touches a dependency -- it just proves the process
can respond. `/v1/readyz` checks the things this service actually needs:
the primary Postgres (`raw.*` writes), the separate logging Postgres
(`meta._ingest_log` close-out, `meta._dbt_build_log`/`meta._retention_
log`/`meta._marts_archive_log` -- its own instance since 2026-08-12,
`LOG_DB_URL`, falls back to the primary database when unset), and
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

from app.api.v1.deps import get_db, get_log_db
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
    log_db: AsyncSession = Depends(get_log_db),
) -> ReadyResponse:
    components = [
        await _check_postgres(db, name="postgres"),
        await _check_postgres(log_db, name="postgres_log"),
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


async def _check_postgres(db: AsyncSession, *, name: str = "postgres") -> ComponentHealth:
    """`name` distinguishes the primary database from the separate
    logging database (`LOG_DB_URL`, 2026-08-12, falls back to the same
    database as `db` when unset)."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        return ComponentHealth(name=name, healthy=False, detail=str(exc))
    return ComponentHealth(name=name, healthy=True)


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
