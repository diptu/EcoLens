"""Route handlers for the warehouse API.

Split across two routers that `app.py` includes into the FastAPI app:
`health_router` (unauthenticated) and `data_router` (requires the API
key when `Settings.api_key` is set). Each handler is a thin call into
`queries.py` — no SQL and no response shaping lives here.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from . import queries
from .db import ConnectionPool
from .dependencies import (
    require_api_key,
    require_pool,
    validate_range_dep,
    validate_region_dep,
    validate_year_dep,
)
from .models import (
    DemandRow,
    DemandSummary,
    GenerationRow,
    HealthResponse,
    HolidayRow,
    Region,
    WeatherRow,
)
from .validation import validate_range, validate_region

# /health is unauthenticated (load balancers / uptime checks hit it) —
# every other route requires the API key when Settings.api_key is set.
health_router = APIRouter()
data_router = APIRouter(dependencies=[Depends(require_api_key)])


@health_router.get("/health", response_model=HealthResponse, tags=["ops"])
async def health(request: Request) -> dict[str, Any]:
    """Liveness + readiness check. Pings the DB and reports pool/cache status."""
    pool: ConnectionPool | None = getattr(request.app.state, "pool", None)
    cache = getattr(request.app.state, "cache", None)
    pg = await pool.health() if pool else {"status": "unavailable"}
    cache_status = (
        {"enabled": cache.enabled, "connected": cache.connected}
        if cache is not None
        else {"enabled": False, "connected": False}
    )
    overall = "ok" if pg.get("status") == "ok" else "degraded"
    return {
        "status": overall,
        "pg": pg,
        "cache": cache_status,
        "uptime_seconds": round(time.time() - request.app.state.start_time, 2),
    }


@data_router.get("/regions", response_model=list[Region], tags=["metadata"])
async def regions(pool: ConnectionPool = Depends(require_pool)) -> list[dict[str, Any]]:
    return await queries.get_regions(pool)


@data_router.get(
    "/regions/{region}/demand", response_model=list[DemandRow], tags=["timeseries"]
)
async def region_demand(
    region: str = Depends(validate_region_dep),
    rng: tuple[datetime, datetime] = Depends(validate_range_dep),
    limit: int = Query(10_000, le=100_000),
    pool: ConnectionPool = Depends(require_pool),
) -> list[dict[str, Any]]:
    since, until = rng
    return await queries.get_demand_timeseries(pool, region, since, until, limit)


@data_router.get(
    "/regions/{region}/generation",
    response_model=list[GenerationRow],
    tags=["timeseries"],
)
async def region_generation(
    region: str = Depends(validate_region_dep),
    rng: tuple[datetime, datetime] = Depends(validate_range_dep),
    limit: int = Query(10_000, le=100_000),
    pool: ConnectionPool = Depends(require_pool),
) -> list[dict[str, Any]]:
    since, until = rng
    return await queries.get_generation_mix(pool, region, since, until, limit)


@data_router.get(
    "/regions/{region}/weather", response_model=list[WeatherRow], tags=["timeseries"]
)
async def region_weather(
    region: str = Depends(validate_region_dep),
    rng: tuple[datetime, datetime] = Depends(validate_range_dep),
    limit: int = Query(10_000, le=100_000),
    pool: ConnectionPool = Depends(require_pool),
) -> list[dict[str, Any]]:
    since, until = rng
    return await queries.get_weather_joined(pool, region, since, until, limit)


@data_router.get(
    "/regions/{region}/summary", response_model=DemandSummary, tags=["aggregates"]
)
async def region_summary(
    region: str = Depends(validate_region_dep),
    rng: tuple[datetime, datetime] = Depends(validate_range_dep),
    pool: ConnectionPool = Depends(require_pool),
) -> dict[str, Any]:
    since, until = rng
    return await queries.get_demand_summary(pool, region, since, until)


@data_router.get("/national/demand", tags=["timeseries"])
async def national_demand(
    rng: tuple[datetime, datetime] = Depends(validate_range_dep),
    limit: int = Query(10_000, le=100_000),
    pool: ConnectionPool = Depends(require_pool),
) -> list[dict[str, Any]]:
    since, until = rng
    return await queries.get_national_demand(pool, since, until, limit)


@data_router.get("/features/demand/v1", tags=["ml"])
async def features_v1(
    request: Request,
    region: str = Query(...),
    since: datetime = Query(...),
    until: datetime = Query(...),
    limit: int = Query(10_000, le=100_000),
    pool: ConnectionPool = Depends(require_pool),
) -> list[dict[str, Any]]:
    """ML feature table for training. 48 lag columns + weather + holiday."""
    validate_region(region, request.app.state.settings)
    validate_range(since, until)
    return await queries.get_ml_features(pool, region, since, until, limit)


@data_router.get("/features/demand/v1/latest", tags=["ml"])
async def features_latest(
    request: Request,
    region: str = Query(...),
    n: int = Query(48, le=336, description="rows; 48=24h, 336=7d"),
    pool: ConnectionPool = Depends(require_pool),
) -> list[dict[str, Any]]:
    """Most recent N rows for inference (feeds the LSTM input window)."""
    validate_region(region, request.app.state.settings)
    return await queries.get_latest_features(pool, region, n)


@data_router.get("/holidays/{year}", response_model=list[HolidayRow], tags=["metadata"])
async def holidays(
    request: Request,
    year: int = Depends(validate_year_dep),
    region: str | None = Query(default=None, description="filter to one region"),
    pool: ConnectionPool = Depends(require_pool),
) -> list[dict[str, Any]]:
    if region:
        validate_region(region, request.app.state.settings)
    return await queries.get_holidays(pool, year, region)


router = APIRouter()
router.include_router(health_router)
router.include_router(data_router)

__all__ = ["router", "health_router", "data_router"]
