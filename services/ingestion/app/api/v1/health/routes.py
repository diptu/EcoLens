"""Liveness/readiness/metrics endpoints.

`/v1/healthz` never touches a dependency -- it just proves the process
can respond. `/v1/readyz` checks the things this service actually needs:
the primary Postgres (`meta.data_sources` reads/writes), the separate
logging Postgres (`meta._ingest_log`/`meta.anomalies`/`meta._feature_
selection_log` writes -- its own instance since 2026-08-12, `LOG_DB_URL`,
falls back to the primary database when unset so this never spuriously
reports two failures for one real outage), Redis (circuit-breaker state,
Phase 1), and RabbitMQ (publishing landed events, Phase 1) --
deliberately **not** MLflow, unlike data-pipeline's equivalent route
(`app/api/v1/health/routes.py`): this service has no ML dependency at
all (`services/ingestion/TODO.md`'s ground truth on scoped config).

`/metrics` (Phase 3, "Publish Prometheus Metrics") renders `app.core.
metrics.REGISTRY` -- the ingest-domain-only subset `_common.standard_run`
populates (`ingest_duration_seconds`/`ingest_rows_total`/
`ingest_failures_total`/`latest_ingest_ts`/`circuit_breaker_state`), no
dbt/ML/forecast metrics since this service has none of those.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db, get_log_db, get_redis_client
from app.core.metrics import metrics_as_text
from app.db.rabbitmq import get_rabbitmq_connection
from app.schemas.health import ComponentHealth, HealthResponse, ReadyResponse, SystemLoadResponse

router = APIRouter(tags=["health"])


@router.get("/v1/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse()


@router.get("/v1/readyz", response_model=ReadyResponse)
async def readyz(
    response: Response,
    db: AsyncSession = Depends(get_db),
    log_db: AsyncSession = Depends(get_log_db),
    redis: Redis = Depends(get_redis_client),
) -> ReadyResponse:
    components = [
        await _check_postgres(db, name="postgres"),
        await _check_postgres(log_db, name="postgres_log"),
        await _check_redis(redis),
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


@router.get("/v1/system/load", response_model=SystemLoadResponse)
async def system_load() -> SystemLoadResponse:
    """Real, not simulated -- `os.getloadavg()` (a thin wrapper over the
    POSIX `getloadavg()` syscall, backed by `/proc/loadavg` on Linux) and
    `/proc/meminfo`, read fresh on every call. Both reflect the whole
    Linux kernel this container runs under, not just this one
    container's own cgroup -- see `SystemLoadResponse`'s own docstring
    for why that's the right scope for this platform's Operational Tasks
    page. No new dependency: both are stdlib/`/proc`, no `psutil`
    needed for numbers this simple."""
    load_1m, load_5m, load_15m = os.getloadavg()
    mem_total_kb, mem_available_kb = _read_meminfo()
    mem_total_mb = mem_total_kb / 1024
    mem_available_mb = mem_available_kb / 1024
    mem_used_pct = (
        100 * (mem_total_kb - mem_available_kb) / mem_total_kb if mem_total_kb else 0.0
    )
    return SystemLoadResponse(
        load_avg_1m=load_1m,
        load_avg_5m=load_5m,
        load_avg_15m=load_15m,
        cpu_count=os.cpu_count() or 1,
        mem_total_mb=mem_total_mb,
        mem_available_mb=mem_available_mb,
        mem_used_pct=mem_used_pct,
    )


def _read_meminfo() -> tuple[float, float]:
    """`(MemTotal_kb, MemAvailable_kb)` from `/proc/meminfo` -- `Avail
    able` (not `MemFree`) is the kernel's own "how much could actually
    be allocated right now" estimate, already accounting for reclaimable
    cache/buffers, which is what a real "% memory used" figure should be
    measured against."""
    total_kb = available_kb = 0.0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                total_kb = float(line.split()[1])
            elif line.startswith("MemAvailable:"):
                available_kb = float(line.split()[1])
    return total_kb, available_kb


async def _check_postgres(db: AsyncSession, *, name: str = "postgres") -> ComponentHealth:
    """`name` distinguishes the primary database from the separate
    logging database (`LOG_DB_URL`, 2026-08-12, falls back to the same
    database as `db` when unset -- in that case this reports the same
    real connectivity twice under two names, which is honest, not
    redundant noise: they really are the same live check until an
    operator actually configures a separate instance)."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        return ComponentHealth(name=name, healthy=False, detail=str(exc))
    return ComponentHealth(name=name, healthy=True)


async def _check_redis(redis: Redis) -> ComponentHealth:
    try:
        await redis.ping()
    except Exception as exc:
        return ComponentHealth(name="redis", healthy=False, detail=str(exc))
    return ComponentHealth(name="redis", healthy=True)


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
