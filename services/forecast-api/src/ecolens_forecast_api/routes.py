"""Route handlers for forecast-api.

`health_router` is unauthenticated (load balancers hit it); `data_router`
requires the API key when `Settings.api_key` is set. Each handler is a
thin call into `queries.py` + `forecasting/baseline.py` -- no SQL and no
forecast math lives here.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from . import queries
from .cache import Cache
from .db import ConnectionPool
from .dependencies import require_api_key, require_pool, validate_region_dep
from .forecasting.baseline import MODEL_NAME as BASELINE_MODEL_NAME
from .forecasting.baseline import forecast_from_latest_row
from .forecasting.lstm_forecast import (
    forecast_from_recent_rows,
    model_name as lstm_model_name,
)
from .forecasting.reload import ModelReloader
from .metrics import record_cache_result, render_metrics, time_forecast_request
from .models import ForecastResponse, HealthResponse
from .settings import ForecastApiSettings
from .validation import validate_horizon

health_router = APIRouter()
data_router = APIRouter(dependencies=[Depends(require_api_key)])


@health_router.get("/health", response_model=HealthResponse, tags=["ops"])
async def health(request: Request) -> dict[str, Any]:
    """Liveness + readiness check. Pings the DB and reports pool/cache/model status.

    Model status is informational only -- a missing/stale model never
    flips `overall` to degraded, since the baseline forecaster keeps
    `/v1/forecast` working either way (ECO-F06); only Postgres being
    down affects `overall`, since baseline itself needs it.
    """
    pool: ConnectionPool | None = getattr(request.app.state, "pool", None)
    cache = getattr(request.app.state, "cache", None)
    reloader: ModelReloader | None = getattr(request.app.state, "reloader", None)
    pg = await pool.health() if pool else {"status": "unavailable"}
    cache_status = (
        {"enabled": cache.enabled, "connected": cache.connected}
        if cache is not None
        else {"enabled": False, "connected": False}
    )
    model_status = _model_health_status(reloader)
    overall = "ok" if pg.get("status") == "ok" else "degraded"
    return {
        "status": overall,
        "pg": pg,
        "cache": cache_status,
        "model": model_status,
        "uptime_seconds": round(time.time() - request.app.state.start_time, 2),
    }


@health_router.get("/metrics", tags=["ops"], include_in_schema=False)
async def metrics() -> Response:
    """Prometheus scrape endpoint (ECO-T02). Unauthenticated, like `/health` --
    scrapers live inside the trust boundary, not behind the forecast API key.
    """
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


def _model_health_status(reloader: ModelReloader | None) -> dict[str, Any]:
    if reloader is None:
        return {
            "loaded": False,
            "version": None,
            "last_reload_at": None,
            "last_reload_success": None,
            "last_reload_error": None,
        }
    state = reloader.state
    return {
        "loaded": state.current is not None,
        "version": state.current.version if state.current else None,
        "last_reload_at": (
            state.last_reload_at.isoformat() if state.last_reload_at else None
        ),
        "last_reload_success": state.last_reload_success,
        "last_reload_error": state.last_reload_error,
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

    ECO-F06: serves real LSTM output (with conformal-calibrated bands)
    when a model is loaded, falling back to the seasonal-naive baseline
    otherwise -- same response contract either way, so API consumers
    never see the difference except in the `model` field.
    """
    settings: ForecastApiSettings = request.app.state.settings
    cache: Cache = request.app.state.cache
    reloader: ModelReloader | None = getattr(request.app.state, "reloader", None)
    resolved_horizon = (
        horizon if horizon is not None else settings.default_horizon_slots
    )
    validate_horizon(resolved_horizon, settings)

    loaded = reloader.state.current if reloader is not None else None
    # Optimistic: what *would* serve this if there's enough history --
    # used only for the cache lookup, which must stay cheap enough to
    # skip needing a working pool on a hit. If it turns out there isn't
    # enough history, the cache *write* below uses the corrected key.
    optimistic_model_name = (
        lstm_model_name(loaded) if loaded is not None else BASELINE_MODEL_NAME
    )

    with time_forecast_request(region):
        cache_key = f"forecast:{optimistic_model_name}:{region}:{resolved_horizon}"
        cached = await cache.get(cache_key)
        record_cache_result(enabled=cache.enabled, hit=cached is not None)
        if cached is not None:
            return cached

        pool: ConnectionPool = require_pool(request)

        if loaded is not None:
            recent_rows = await queries.get_recent_feature_rows(
                pool, region, settings.model_lookback
            )
            if len(recent_rows) < settings.model_lookback:
                # Not enough history for this region yet (e.g. a newly
                # onboarded region) -- degrade to baseline rather than
                # error, same as an unloaded model would.
                loaded = None

        if loaded is not None:
            active_model_name = lstm_model_name(loaded)
            steps = forecast_from_recent_rows(
                loaded,
                recent_rows,
                lookback=settings.model_lookback,
                horizon=resolved_horizon,
                interval_minutes=settings.interval_minutes,
            )
            as_of = recent_rows[-1]["ts_30"]
        else:
            active_model_name = BASELINE_MODEL_NAME
            row = await queries.get_latest_feature_row(pool, region)
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"no feature data available yet for {region!r}",
                )
            steps = forecast_from_latest_row(
                row,
                horizon=resolved_horizon,
                interval_minutes=settings.interval_minutes,
                z_score=settings.interval_z_score,
            )
            as_of = row["ts_30"]

        response = {
            "region": region,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "as_of": as_of,
            "model": active_model_name,
            "interval_minutes": settings.interval_minutes,
            "steps": steps,
        }
        final_cache_key = f"forecast:{active_model_name}:{region}:{resolved_horizon}"
        await cache.set(final_cache_key, response, ttl=settings.cache_ttl_seconds)
        return response


router = APIRouter()
router.include_router(health_router)
router.include_router(data_router)

__all__ = ["router", "health_router", "data_router"]
