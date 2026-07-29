"""Route handlers for forecast-api.

`health_router` is unauthenticated (load balancers hit it); `data_router`
requires the API key when `Settings.api_key` is set. Each handler is a
thin call into `queries.py` + `forecasting/baseline.py` -- no SQL and no
forecast math lives here.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from . import queries
from .cache import Cache
from .db import ConnectionPool
from .dependencies import require_api_key, require_pool, validate_region_dep
from .forecasting.baseline import MODEL_NAME as BASELINE_MODEL_NAME
from .forecasting.baseline import forecast_from_latest_row
from .forecasting.carbon import compute_carbon_metrics
from .forecasting.fuel_forecast import forecast_source_breakdown
from .forecasting.fuel_loader import LoadedFuelEnsemble
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


async def _forecast_for_region(
    request: Request,
    pool: ConnectionPool,
    region: str,
    resolved_horizon: int,
) -> dict[str, Any]:
    """Builds one region's full forecast response (`total_demand_mw` +
    `source_breakdown_mw` + `carbon_metrics` + `weather_context`) -- no
    caching here, that's each *caller's* concern: `forecast()` and
    `forecast_national()` below cache under different keys (per-region
    vs. a single national key), so mixing a cache read/write into this
    shared builder would force one cache strategy on both.

    ECO-F06: serves real LSTM output (with conformal-calibrated bands)
    when a model is loaded, falling back to the seasonal-naive baseline
    otherwise -- same response contract either way, so API consumers
    never see the difference except in the `model` field.

    Root TODO.md's "API & Registry Serving": each step also carries
    `source_breakdown_mw` (16-fuel mix, root TODO.md's Normalization
    Constraint Layer) and `carbon_metrics` (deterministic, root TODO.md's
    Deterministic Carbon Accounting) whenever the fuel ensemble is
    loaded, `None` otherwise -- same graceful-degradation contract the
    LSTM/baseline split above already uses. `weather_context` (current
    conditions, not a forecast) is populated whenever a feature row was
    read at all, independent of which forecaster/ensemble is loaded.
    """
    settings: ForecastApiSettings = request.app.state.settings
    reloader: ModelReloader | None = getattr(request.app.state, "reloader", None)
    loaded = reloader.state.current if reloader is not None else None

    if loaded is not None:
        recent_rows = await queries.get_recent_feature_rows(
            pool, region, settings.model_lookback
        )
        if len(recent_rows) < settings.model_lookback:
            # Not enough history for this region yet (e.g. a newly
            # onboarded region) -- degrade to baseline rather than
            # error, same as an unloaded model would.
            loaded = None

    # Full FEATURE_COLUMNS row used for weather_context and the fuel
    # ensemble's nowcast (root TODO.md's "API & Registry Serving")
    # regardless of which point forecaster serves total_demand_mw --
    # the LSTM path's recent_rows already carries it; the baseline
    # path's own query (_BASELINE_FEATURE_COLUMNS) doesn't, so it
    # needs a small separate fetch.
    full_feature_row: dict[str, Any] | None = None

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
        full_feature_row = recent_rows[-1]
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
        weather_only_rows = await queries.get_recent_feature_rows(pool, region, 1)
        full_feature_row = weather_only_rows[-1] if weather_only_rows else None

    weather_context = (
        {
            "temp_c": full_feature_row.get("temp_c"),
            "humidity_pct": full_feature_row.get("humidity_pct"),
            "wind_speed_kmh": full_feature_row.get("wind_speed_kmh"),
        }
        if full_feature_row is not None
        else None
    )

    fuel_ensemble: LoadedFuelEnsemble | None = getattr(
        request.app.state, "fuel_ensemble", None
    )
    if fuel_ensemble is not None and full_feature_row is not None:
        breakdown_and_carbon = forecast_source_breakdown(
            fuel_ensemble,
            full_feature_row,
            step_p50_values=[step["p50"] for step in steps],
            interval_minutes=settings.interval_minutes,
        )
        for step, (breakdown, carbon) in zip(steps, breakdown_and_carbon, strict=True):
            step["source_breakdown_mw"] = breakdown
            step["carbon_metrics"] = (
                dataclasses.asdict(carbon) if carbon is not None else None
            )

    return {
        "region": region,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "as_of": as_of,
        "model": active_model_name,
        "interval_minutes": settings.interval_minutes,
        "steps": steps,
        "weather_context": weather_context,
    }


def _combine_national(
    per_region: list[dict[str, Any]],
    settings: ForecastApiSettings,
) -> dict[str, Any]:
    """Root TODO.md's Dashboard/Executive section, Tier 1: Executive is a
    portfolio/national view, but `/v1/forecast/{region}` only ever
    answers for one region. Chose the backend-endpoint option (not a
    frontend fan-out over 6 calls) so this approximation is documented
    and computed in exactly one place.

    `p10`/`p50`/`p90` are summed across regions per matching horizon
    step -- a **conservative sum-of-bands**, not a true joint quantile
    across 6 regions (which would need each region's forecast-error
    correlation structure this service has no way to estimate; summing
    the edges is the standard, simpler approximation portfolio-level
    dashboards use instead). `source_breakdown_mw` sums per fuel across
    regions, and `carbon_metrics` is *recomputed* from that summed
    national mix (`compute_carbon_metrics`) rather than averaging each
    region's own metrics -- `renewable_proportion`/intensity aren't
    additive, so this is the only way to get a correct national figure,
    not a shortcut.

    `weather_context` is `None` -- there's no single meaningful
    "national" temperature/humidity/wind value the way one region has
    its own current conditions.
    """
    n_steps = min(len(r["steps"]) for r in per_region)
    interval_hours = settings.interval_minutes / 60.0

    combined_steps: list[dict[str, Any]] = []
    for i in range(n_steps):
        step_group = [r["steps"][i] for r in per_region]

        combined_breakdown: dict[str, float] | None = None
        combined_carbon: dict[str, float] | None = None
        breakdowns = [
            s["source_breakdown_mw"] for s in step_group if s.get("source_breakdown_mw")
        ]
        if breakdowns:
            combined_breakdown = {}
            for breakdown in breakdowns:
                for fuel, mw in breakdown.items():
                    combined_breakdown[fuel] = combined_breakdown.get(fuel, 0.0) + mw
            combined_carbon = dataclasses.asdict(
                compute_carbon_metrics(
                    combined_breakdown, interval_hours=interval_hours
                )
            )

        combined_steps.append(
            {
                "ts": step_group[0]["ts"],
                "horizon_step": step_group[0]["horizon_step"],
                "p10": sum(s["p10"] for s in step_group if s["p10"] is not None),
                "p50": sum(s["p50"] for s in step_group if s["p50"] is not None),
                "p90": sum(s["p90"] for s in step_group if s["p90"] is not None),
                "source_breakdown_mw": combined_breakdown,
                "carbon_metrics": combined_carbon,
            }
        )

    # Every region's response was built against the same
    # `reloader.state.current` snapshot this request cycle, so they
    # normally all report the same model -- but a region with too
    # little history degrades to baseline independently (see
    # `_forecast_for_region`), so a mixed result is possible and
    # reported honestly rather than silently picking one region's model
    # name for the whole country.
    model_names = {r["model"] for r in per_region}
    model_name = model_names.pop() if len(model_names) == 1 else "mixed"

    return {
        "region": "NATIONAL",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "as_of": min(r["as_of"] for r in per_region),
        "model": model_name,
        "interval_minutes": settings.interval_minutes,
        "steps": combined_steps,
        "weather_context": None,
    }


@data_router.get(
    "/v1/forecast/national", response_model=ForecastResponse, tags=["forecast"]
)
async def forecast_national(
    request: Request,
    horizon: int | None = Query(
        default=None, description="30-min steps ahead, 1-48 (default: settings)"
    ),
) -> dict[str, Any]:
    """Registered *before* `/v1/forecast/{region}` below in this file --
    FastAPI/Starlette matches routes in registration order, and
    `{region}` would otherwise greedily match the literal path segment
    `"national"` as a region name (and 400 on it via
    `validate_region_dep`) before this route ever got a chance.

    A region with no feature data yet is skipped (not a 404 for the
    whole national view -- one newly-onboarded region without history
    shouldn't take down the portfolio view); 404s only if *every* region
    has nothing to report.
    """
    settings: ForecastApiSettings = request.app.state.settings
    cache: Cache = request.app.state.cache
    resolved_horizon = (
        horizon if horizon is not None else settings.default_horizon_slots
    )
    validate_horizon(resolved_horizon, settings)

    with time_forecast_request("NATIONAL"):
        # One cache key, independent of any per-region cache entries --
        # see _combine_national's docstring on why this can't just reuse
        # forecast()'s own per-region cache reads.
        cache_key = f"forecast:national:{resolved_horizon}"
        cached = await cache.get(cache_key)
        record_cache_result(enabled=cache.enabled, hit=cached is not None)
        if cached is not None:
            return cached

        pool: ConnectionPool = require_pool(request)
        per_region: list[dict[str, Any]] = []
        for region in settings.valid_regions:
            try:
                per_region.append(
                    await _forecast_for_region(request, pool, region, resolved_horizon)
                )
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                continue

        if not per_region:
            raise HTTPException(
                status_code=404,
                detail="no feature data available yet for any region",
            )

        response = _combine_national(per_region, settings)
        await cache.set(cache_key, response, ttl=settings.cache_ttl_seconds)
        return response


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
        response = await _forecast_for_region(request, pool, region, resolved_horizon)

        final_cache_key = f"forecast:{response['model']}:{region}:{resolved_horizon}"
        await cache.set(final_cache_key, response, ttl=settings.cache_ttl_seconds)
        return response


router = APIRouter()
router.include_router(health_router)
router.include_router(data_router)

__all__ = ["router", "health_router", "data_router"]
