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

from fastapi import APIRouter, Depends, Query, Request, Response

from ecolens.warehouse.repository import queries
from ecolens.warehouse.db.connection import ConnectionPool
from ecolens.warehouse.schema.api_responses import (
    DemandRow,
    DemandSummary,
    ExecutiveKpisResponse,
    GenerationRow,
    HealthResponse,
    NationalDailyEmissionsRow,
    NationalGenerationMix,
    NationalSummary,
    PaginatedHolidays,
    Region,
    WeatherRow,
)
from ecolens.warehouse.core.validation import validate_range, validate_region
from ecolens.warehouse.service.executive_kpis import build_executive_kpis

from .read_dependencies import (
    require_api_key,
    require_pool,
    validate_analytics_region_dep,
    validate_currency_dep,
    validate_period_dep,
    validate_range_dep,
    validate_region_dep,
    validate_year_dep,
)

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


@data_router.get(
    "/national/summary", response_model=NationalSummary, tags=["aggregates"]
)
async def national_summary(
    rng: tuple[datetime, datetime] = Depends(validate_range_dep),
    pool: ConnectionPool = Depends(require_pool),
) -> dict[str, Any]:
    """Root TODO.md's Dashboard/Executive Tier 2: a single national
    number over an arbitrary date range, including real mass emissions
    (tCO2e) -- what the KPI row's "Total CO2e", "Carbon Intensity", and
    "Renewable Share" cards should call, once each with the current
    period's `since`/`until` and once with the prior period's, per that
    same TODO item's "vs. last period" delta-methodology decision (day-
    over-day for a 24h-scoped card, YTD-vs-prior-YTD for a YTD-scoped
    one -- this endpoint doesn't pick that for the caller, since the two
    scopes need genuinely different `since`/`until` pairs).
    """
    since, until = rng
    return await queries.get_national_summary(pool, since, until)


@data_router.get(
    "/national/emissions/daily",
    response_model=list[NationalDailyEmissionsRow],
    tags=["aggregates"],
)
async def national_daily_emissions(
    since: datetime = Query(...),
    limit: int = Query(90, le=366),
    pool: ConnectionPool = Depends(require_pool),
) -> list[dict[str, Any]]:
    """Root TODO.md's Dashboard/Executive Tier 2: the trend chart's
    "Actual" line -- daily-bucketed national totals from
    `mv_daily_national_emissions`, not a live aggregate over
    `fact_demand_30min` (a materialized view refreshed on dbt build,
    same reasoning `mv_daily_national_demand` already exists for: this
    is meant to be cheap to call from a dashboard on every page load,
    not recomputed from the 30-min fact table each time).
    """
    return await queries.get_national_daily_emissions(pool, since.date(), limit)


@data_router.get(
    "/national/generation-mix",
    response_model=NationalGenerationMix,
    tags=["aggregates"],
)
async def national_generation_mix(
    rng: tuple[datetime, datetime] = Depends(validate_range_dep),
    pool: ConnectionPool = Depends(require_pool),
) -> dict[str, Any]:
    """Root TODO.md's Dashboard/Executive Tier 2: the "Emissions by
    Source" donut's Grid Electricity slice -- national (all-region)
    fuel-mix MW totals and shares over `[since, until)`. Interpretation
    (a) from that TODO item (the grid's own generation mix), not (b)
    (a specific customer's purchased-electricity attribution, which
    needs the not-yet-built customer-meter ingestion in that item's
    Tier 3 cross-reference).
    """
    since, until = rng
    return await queries.get_national_generation_mix(pool, since, until)


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


@data_router.get(
    "/holidays/{year}", response_model=PaginatedHolidays, tags=["metadata"]
)
async def holidays(
    request: Request,
    year: int = Depends(validate_year_dep),
    region: str | None = Query(default=None, description="filter to one region"),
    limit: int = Query(100, ge=1, le=500, description="rows per page"),
    offset: int = Query(0, ge=0, description="rows to skip"),
    pool: ConnectionPool = Depends(require_pool),
) -> dict[str, Any]:
    if region:
        validate_region(region, request.app.state.settings)
    items, total = await queries.get_holidays(
        pool, year, region, limit=limit, offset=offset
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@data_router.get(
    "/api/analytics/executive-kpis",
    response_model=ExecutiveKpisResponse,
    tags=["analytics"],
)
async def executive_kpis(
    request: Request,
    response: Response,
    period: str = Depends(validate_period_dep),
    region: str = Depends(validate_analytics_region_dep),
    currency: str = Depends(validate_currency_dep),
    pool: ConnectionPool = Depends(require_pool),
) -> dict[str, Any]:
    """Powers the 6 KPI cards at the top of `/dashboard/executive/` --
    see `service/executive_kpis.py`'s own docstring for what's real vs.
    a documented "not yet available" stub, and for the auth deviation
    from that endpoint's own spec (reuses this router's existing
    `require_api_key` gate, not JWT).
    """
    cache = getattr(request.app.state, "cache", None)
    payload, cache_hit = await build_executive_kpis(
        pool, cache, period=period, region=region, currency=currency
    )

    response.headers["Cache-Control"] = "private, max-age=60"
    response.headers["X-Cache"] = "HIT" if cache_hit else "MISS"
    request_id = request.headers.get("X-Request-Id")
    if request_id:
        response.headers["X-Request-Id"] = request_id

    return payload


router = APIRouter()
router.include_router(health_router)
router.include_router(data_router)

__all__ = ["router", "health_router", "data_router"]
