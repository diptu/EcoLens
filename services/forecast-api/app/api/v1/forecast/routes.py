"""`GET /v1/forecast` (`README.md` § API reference) — the actual
DemandLSTM inference path.

**v0 doesn't resample to an arbitrary requested `horizon`/`interval`.**
The model was trained on, and only ever predicts, its source region's
native cadence and a fixed `horizon` (48 native steps — 4h for a 5-min
NEM region like NSW1, 24h for a 30-min WEM region). `horizon`/`interval`
query params are accepted (so a client following `README.md`'s
documented contract doesn't get a 422) but are entirely ignored — the
response always reports the model's *real* cadence in its own
`horizon`/`interval` fields (`ForecastResponse`'s docstring), not an echo
of the request. Building real resampling/interpolation to an arbitrary
requested interval is future work, not silently faked here.

**`region=NEM`** is a special case: it sums the 5 NEM regions' forecasts
point-for-point (`_run_nem_aggregate_forecast`) rather than running
inference against a `region` column value of "NEM" (there is no such
region in the warehouse). WEM is excluded from that sum -- its 30-min/24h
native cadence can't be summed against NEM's 5-min/4h one without the
same resampling this module doesn't build. There is still no true
NEM+WEM whole-of-market aggregate.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import torch
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    get_app_settings,
    get_db,
    get_model_registry,
    get_redis_client,
)
from app.core.errors import ApiError
from app.core.logging import get_logger
from app.core.metrics import forecast_predictions_total, forecast_prediction_latency_seconds
from app.core.tracing import get_tracer
from app.schemas.forecast import ForecastPoint, ForecastResponse
from app.core.config import Settings
from app.service.ml.adaptive_calibration import get_calibration_scale
from app.service.ml.data import load_holidays, load_latest_window
from app.service.ml.evaluate import BaselineForecaster, _infer_period_steps
from app.service.ml.features import (
    FEATURE_COLUMNS,
    NUMERIC_COLUMNS,
    build_features,
)
from app.models.ml import DemandForecast
from app.service.ml.forecast_breaker import OPEN, ForecastCircuitBreaker
from app.service.ml.forecast_reconciliation import breaker_name, record_served_forecast
from app.service.ml.registry import ModelBundle, ModelRegistry

router = APIRouter(prefix="/v1", tags=["forecast"])
log = get_logger(__name__)
tracer = get_tracer()

# The 5 NEM regions -- same 5-min AEMO dispatch clock, same 48-step/4h
# native horizon, so `region=NEM` (`_run_nem_aggregate_forecast`) can sum
# them point-for-point. WEM is deliberately excluded: its 30-min cadence
# and 24h horizon can't be summed against NEM's without the resampling
# this service explicitly doesn't build (see module docstring). Static,
# same reasoning as `api/v1/regions/routes.py`'s own static region list --
# no region has ever been added without a code change elsewhere either.
_NEM_AGGREGATE_REGIONS: tuple[str, ...] = ("NSW1", "QLD1", "VIC1", "SA1", "TAS1")

# max(lags + rolling windows) from ml/features.py -- the number of extra
# historical rows needed before a `lookback`-sized window so every row in
# that window has fully-populated (non-NaN) lag/rolling features once
# `build_features` runs. Kept in sync by hand with `service/ml/features.py`'s
# `_LAGS`/`_ROLLING_WINDOWS` (12 and 24 respectively) -- see that file's
# duplication note.
_FEATURE_WARMUP_ROWS = 24


def _inverse_target(scaler, values: np.ndarray) -> np.ndarray:
    shape = values.shape
    return scaler.inverse_transform(values.reshape(-1, 1)).reshape(shape)


def _infer_step(ts: pd.Series) -> timedelta:
    """Median gap between consecutive timestamps in `ts` — robust to an
    occasional missing interval, unlike just diffing the last two rows."""
    diffs = ts.diff().dropna()
    if diffs.empty:
        raise ApiError(
            503, "insufficient_data", "not enough recent rows to infer a time step"
        )
    return pd.Timedelta(diffs.median()).to_pytimedelta()


def _format_timedelta(delta: timedelta) -> str:
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes % 60 == 0 and total_minutes >= 60:
        return f"{total_minutes // 60}h"
    return f"{total_minutes}m"


async def _run_inference(
    db: AsyncSession, bundle: ModelBundle, region: str
) -> tuple[DemandForecast, pd.Series]:
    n_rows = bundle.lookback + _FEATURE_WARMUP_ROWS
    raw_df = await load_latest_window(db, region, n_rows)
    if len(raw_df) < n_rows:
        raise ApiError(
            503,
            "insufficient_data",
            f"Not enough recent warehouse data for region '{region}' to build a forecast "
            f"(need {n_rows} rows, have {len(raw_df)})",
        )

    holidays = await load_holidays(db)
    engineered = build_features(raw_df, holidays=holidays)
    window = engineered.tail(bundle.lookback)

    feature_matrix = window[list(FEATURE_COLUMNS)]
    if feature_matrix.isna().any().any():
        raise ApiError(
            503,
            "insufficient_data",
            f"Recent data for region '{region}' has gaps -- cannot build a full feature window",
        )

    feature_scaler = bundle.feature_scalers.get(region)
    if feature_scaler is None:
        raise ApiError(
            503,
            "model_not_trained_for_region",
            f"The currently-served model has no fitted feature scaler for region '{region}' "
            "(it wasn't trained on this region)",
        )

    # The scaler was only ever fit on `NUMERIC_COLUMNS` (data-pipeline's
    # `service/ml/data.py`'s `fit_scalers`) -- cyclical/flag columns in
    # `FEATURE_COLUMNS` were never scaled at training time either, so
    # transforming the *full* feature matrix through it would both raise
    # (wrong column count) and be wrong even if it didn't. Scale just the
    # numeric subset, in place, then take the full `FEATURE_COLUMNS`-
    # ordered matrix the model actually expects as input.
    scaled_window = window.copy()
    scaled_window[list(NUMERIC_COLUMNS)] = feature_scaler.transform(
        window[list(NUMERIC_COLUMNS)].to_numpy()
    )
    # `FEATURE_COLUMNS` spans both float (scaled numeric + cyclical) and
    # bool (`is_weekend`/`is_holiday`) columns -- `.to_numpy()` without an
    # explicit dtype can come back `object`-dtype for a mixed selection
    # like this, which `torch.tensor` then refuses outright. Force a
    # uniform float dtype explicitly rather than relying on pandas'
    # column-mix type inference.
    scaled = scaled_window[list(FEATURE_COLUMNS)].to_numpy(dtype=np.float64)
    x = torch.tensor(scaled, dtype=torch.float32).unsqueeze(0)

    bundle.model.eval()
    with torch.no_grad():
        out = bundle.model(x)

    return out, window["ts"]


#: `(p10, p50, p90, step, last_ts)` -- the raw demand-forecast arrays
#: before they're formatted into a `ForecastResponse`. Exposed so
#: `app.api.v1.emissions.routes`'s `GET /v1/emissions/forecast` can
#: derive an emissions projection (demand x current intensity) from the
#: exact same inference this module's own `/v1/forecast` route serves,
#: without re-running or duplicating it.
ForecastArrays = tuple[np.ndarray, np.ndarray, np.ndarray, timedelta, datetime]


def _build_response(
    region: str,
    settings: Settings,
    bundle: ModelBundle,
    lo: np.ndarray,
    p50: np.ndarray,
    hi: np.ndarray,
    step: timedelta,
    last_ts: datetime,
) -> ForecastResponse:
    points = [
        ForecastPoint(
            ts=last_ts + step * (i + 1),
            p10=round(float(lo[0, i]), 1),
            p50=round(float(p50[0, i]), 1),
            p90=round(float(hi[0, i]), 1),
        )
        for i in range(bundle.horizon)
    ]
    return ForecastResponse(
        region=region,
        model=f"{settings.mlflow_registry_model_name}@{bundle.stage.lower()}",
        generated_at=datetime.now(UTC),
        horizon=_format_timedelta(step * bundle.horizon),
        interval=_format_timedelta(step),
        points=points,
    )


async def _forecast_arrays_single_region(
    db: AsyncSession, bundle: ModelBundle, region: str
) -> ForecastArrays:
    out, window_ts = await _run_inference(db, bundle, region)

    p10 = _inverse_target(bundle.target_scaler, out.p10.numpy())
    p50 = _inverse_target(bundle.target_scaler, out.p50.numpy())
    p90 = _inverse_target(bundle.target_scaler, out.p90.numpy())
    lo, hi = bundle.calibration.apply(p10, p90)

    step = _infer_step(window_ts)
    last_ts = window_ts.iloc[-1].to_pydatetime()
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=UTC)

    return lo, p50, hi, step, last_ts


async def _forecast_arrays_nem(db: AsyncSession, bundle: ModelBundle) -> ForecastArrays:
    """`region=NEM` sums demand P10/P50/P90 across the 5 NEM regions
    (`_NEM_AGGREGATE_REGIONS`) point-for-point -- valid because they all
    share the same 5-min AEMO dispatch clock and the same 48-step/4h
    native horizon (see that constant's docstring for why WEM can't join
    this sum). Summing is by step *index*, not by re-matching timestamps
    -- if one region's data is staler than the others at request time,
    this silently under/overstates that region's contribution rather than
    erroring, the same caveat `load_latest_window`'s single-region
    cross-context features already carry.
    """
    per_region: list[ForecastArrays] = []
    for region in _NEM_AGGREGATE_REGIONS:
        per_region.append(await _forecast_arrays_single_region(db, bundle, region))

    lo_sum = np.sum([r[0] for r in per_region], axis=0)
    p50_sum = np.sum([r[1] for r in per_region], axis=0)
    hi_sum = np.sum([r[2] for r in per_region], axis=0)
    # The freshest region's clock becomes the aggregate's own -- the
    # others' step indices still line up against it (same cadence, same
    # underlying 5-min AEMO clock).
    step, last_ts = max(((r[3], r[4]) for r in per_region), key=lambda r: r[1])

    return lo_sum, p50_sum, hi_sum, step, last_ts


async def _run_single_region_forecast(
    db: AsyncSession, bundle: ModelBundle, settings: Settings, region: str, redis: Redis
) -> ForecastResponse:
    lo, p50, hi, step, last_ts = await _forecast_arrays_single_region(
        db, bundle, region
    )
    # `TODO.md` Forecasting Phase 4's adaptive-bound-tightening item --
    # `adaptive_calibration.py`'s scale, driven by how often this exact
    # `(model, region)`'s previously-served intervals actually contained
    # what happened. Applied symmetrically around `p50` (the point
    # estimate itself is never touched, only the interval width) --
    # `region == "NEM"` is excluded the same way the circuit
    # breaker/fallback above is: an aggregate of 5 independently-scaled
    # regions summed together isn't what this scale was fit against.
    scale = await get_calibration_scale(redis, settings.mlflow_registry_model_name, region)
    if scale != 1.0:
        lo = p50 - (p50 - lo) * scale
        hi = p50 + (hi - p50) * scale
    return _build_response(region, settings, bundle, lo, p50, hi, step, last_ts)


async def _run_nem_aggregate_forecast(
    db: AsyncSession, bundle: ModelBundle, settings: Settings
) -> ForecastResponse:
    lo, p50, hi, step, last_ts = await _forecast_arrays_nem(db, bundle)
    return _build_response("NEM", settings, bundle, lo, p50, hi, step, last_ts)


#: Rows fetched for the seasonal-naive fallback's own history pool --
#: generous enough to cover `BaselineForecaster`'s default `n_periods=8`
#: at NEM's real 5-min cadence (8 * 288 = 2304 rows/day-periods), the
#: most demanding case; a 30-min WEM region ends up with more pooled
#: history than it strictly needs, which is harmless.
_BASELINE_FALLBACK_HISTORY_ROWS = 2500


async def _run_baseline_fallback_forecast(
    db: AsyncSession, settings: Settings, bundle: ModelBundle, region: str
) -> ForecastResponse:
    """Served instead of the real model when `region`'s forecast-quality
    circuit breaker (`service/ml/forecast_breaker.py`) is open --
    `TODO.md` Forecasting Phase 4's "instantaneous fallback... to a
    pre-validated statistical baseline model". Uses the same real,
    already-built `BaselineForecaster`/`_infer_period_steps` this
    service's own walk-forward evaluation harness (`service/ml/
    evaluate.py`) scores every model against -- not a second, separately
    written baseline implementation.
    """
    raw_df = await load_latest_window(db, region, _BASELINE_FALLBACK_HISTORY_ROWS)
    if len(raw_df) < 2:
        raise ApiError(
            503,
            "insufficient_data",
            f"Not enough recent warehouse data for region '{region}' to build "
            "even a baseline fallback forecast",
        )
    period_steps = _infer_period_steps(raw_df)
    forecaster = BaselineForecaster(period_steps=period_steps)
    p10, p50, hi = forecaster.predict(raw_df, horizon=bundle.horizon)

    step = _infer_step(raw_df["ts"])
    last_ts = raw_df["ts"].iloc[-1].to_pydatetime()
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=UTC)

    response = _build_response(
        region,
        settings,
        bundle,
        p10.reshape(1, -1),
        p50.reshape(1, -1),
        hi.reshape(1, -1),
        step,
        last_ts,
    )
    response.model = forecaster.name
    response.served_by = "baseline_fallback"
    return response


@router.get("/forecast", response_model=ForecastResponse)
async def get_forecast(
    region: str,
    horizon: str | None = None,
    interval: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    registry: ModelRegistry = Depends(get_model_registry),
    settings: Settings = Depends(get_app_settings),
) -> ForecastResponse:
    bundle = registry.bundle
    if bundle is None:
        raise ApiError(
            503, "model_not_loaded", "No Production model version is loaded yet"
        )

    # `TODO.md` Forecasting Phase 4's fallback mechanism -- checked before
    # the cache lookup below, since a cached *model* response from before
    # the breaker tripped shouldn't keep being served once it's open, and
    # a cached *baseline* response from while it was open shouldn't keep
    # being served once it recovers. `region == "NEM"` (the 5-region sum)
    # is deliberately excluded -- checking/serving a fallback for an
    # aggregate of 5 independently-breakered regions is real added scope
    # this pass doesn't cover; NEM always uses the real model.
    is_fallback = False
    if region != "NEM":
        breaker = ForecastCircuitBreaker(
            breaker_name(settings.mlflow_registry_model_name, region), redis
        )
        is_fallback = await breaker.state == OPEN

    # Times the whole handler (cache hit or miss alike) rather than just
    # the inference branch below -- a cache hit's near-zero latency is
    # itself a meaningful data point (proves the cache is doing its job),
    # not noise to exclude. `cache` label on forecast_predictions_total
    # is how a Grafana panel tells hits from misses apart if it needs to.
    with forecast_prediction_latency_seconds.labels(region=region).time():
        cache_key = (
            f"forecast:v1:{region}:baseline_fallback"
            if is_fallback
            else f"forecast:v1:{region}:{bundle.version}"
        )
        cached = await redis.get(cache_key)
        if cached is not None:
            forecast_predictions_total.labels(region=region, cache="hit").inc()
            return ForecastResponse.model_validate_json(cached)

        # Real inference/fallback branch (`TODO.md` Forecasting Phase 7's
        # "OpenTelemetry Instrumentation" + "Structured Logging" -- a
        # cache hit above never reaches here, since there's no model
        # execution/drift-relevant work to trace or log for it; the
        # `cache="hit"` metric label already covers that case).
        with tracer.start_as_current_span(
            "forecast_api.get_forecast",
            attributes={
                "region": region,
                "served_by": "baseline_fallback" if is_fallback else "model",
            },
        ) as span:
            inference_started = time.perf_counter()
            if is_fallback:
                response = await _run_baseline_fallback_forecast(
                    db, settings, bundle, region
                )
            elif region == "NEM":
                response = await _run_nem_aggregate_forecast(db, bundle, settings)
            else:
                response = await _run_single_region_forecast(
                    db, bundle, settings, region, redis
                )
                # Logs the shortest-horizon point for later reconciliation
                # against real demand (`service/ml/forecast_reconciliation.py`'s
                # background sweep) -- only for a real (non-fallback) model
                # response; there's no point reconciling a baseline forecast
                # against itself. `p10_mw`/`p90_mw` are the *already-scaled*
                # bounds `_run_single_region_forecast` just applied above --
                # `adaptive_calibration.py`'s own docstring explains why it
                # has to adapt against what was actually served, not the
                # raw pre-scale conformal width.
                if response.points:
                    await record_served_forecast(
                        redis,
                        model_name=settings.mlflow_registry_model_name,
                        region=region,
                        target_ts=response.points[0].ts,
                        p50_mw=response.points[0].p50,
                        p10_mw=response.points[0].p10,
                        p90_mw=response.points[0].p90,
                    )
            inference_duration = time.perf_counter() - inference_started

            span.set_attribute("model_version", response.model)
            span.set_attribute("forecast_horizon", response.horizon)
            span.set_attribute("inference_duration", inference_duration)
            log.info(
                "forecast.served",
                region=region,
                model_version=response.model,
                forecast_horizon=response.horizon,
                inference_duration=inference_duration,
                served_by=response.served_by,
            )

        await redis.set(
            cache_key, response.model_dump_json(), ex=settings.forecast_cache_ttl_seconds
        )
        forecast_predictions_total.labels(region=region, cache="miss").inc()
        return response
