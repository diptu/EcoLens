"""Route handlers for forecast-api.

`health_router` is unauthenticated (load balancers hit it); `data_router`
requires the API key when `Settings.api_key` is set. Each handler is a
thin call into `queries.py` + `forecasting/baseline.py` -- no SQL and no
forecast math lives here.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from . import queries
from .cache import Cache
from .db import ConnectionPool
from .dependencies import require_api_key, require_pool, validate_region_dep
from .forecasting.baseline import MODEL_NAME, forecast_from_latest_row
from .models import ForecastResponse, HealthResponse
from .settings import ForecastApiSettings
from .validation import validate_horizon

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


@data_router.get(
    "/v1/forecast/{region}", response_model=ForecastResponse, tags=["forecast"]
)
async def forecast(
    request: Request,
    region: str = Depends(validate_region_dep),
    horizon: int | None = Query(
        default=None, description="30-min steps ahead, 1-48 (default: settings)"
    ),
) -> dict[str, Any]:
    """`require_pool` is checked manually (not via `Depends`) so a cache
    hit can return before ever needing a working pool -- the whole point
    of caching this route.
    """
    settings: ForecastApiSettings = request.app.state.settings
    cache: Cache = request.app.state.cache
    resolved_horizon = (
        horizon if horizon is not None else settings.default_horizon_slots
    )
    validate_horizon(resolved_horizon, settings)

    cache_key = f"forecast:{MODEL_NAME}:{region}:{resolved_horizon}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    pool: ConnectionPool = require_pool(request)
    row = await queries.get_latest_feature_row(pool, region)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"no feature data available yet for {region!r}"
        )

    steps = forecast_from_latest_row(
        row,
        horizon=resolved_horizon,
        interval_minutes=settings.interval_minutes,
        z_score=settings.interval_z_score,
    )
    response = {
        "region": region,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "as_of": row["ts_30"],
        "model": MODEL_NAME,
        "interval_minutes": settings.interval_minutes,
        "steps": steps,
    }
    await cache.set(cache_key, response, ttl=settings.cache_ttl_seconds)
    return response


router = APIRouter()
router.include_router(health_router)
router.include_router(data_router)

__all__ = ["router", "health_router", "data_router"]
