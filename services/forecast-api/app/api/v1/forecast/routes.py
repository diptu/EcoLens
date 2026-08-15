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
from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    get_app_settings,
    get_db,
    get_model_registry,
    get_redis_client,
)
from app.core.errors import ApiError
from app.core.local_cache import TTLCache
from app.core.logging import get_logger
from app.core.metrics import forecast_predictions_total, forecast_prediction_latency_seconds
from app.core.tracing import get_tracer
from app.schemas.forecast import (
    ForecastPoint,
    ForecastResponse,
    RecentBacktestPointOut,
    RecentBacktestResponse,
)
from app.core.config import Settings
from app.service.ml.adaptive_calibration import get_calibration_scale
from app.service.ml.data import load_holidays, load_latest_window
from app.service.ml.evaluate import (
    BaselineForecaster,
    LSTMForecaster,
    RecentBacktestPoint,
    _infer_period_steps,
    evaluate_recent_actual_vs_predicted,
)
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

# L1 cache in front of `GET /v1/forecast`'s existing Redis L2 cache below
# -- same cache keys, same `forecast_cache_ttl_seconds` TTL, just skipping
# the Redis round-trip/JSON parse for a repeat request this same worker
# already served recently. Small `maxsize`: the real key space is just
# (region, model_version | "baseline_fallback"), a handful of entries at
# any moment, never unbounded. Public (not `_`-prefixed) so
# `app.service.cache_warmer`'s forced-refresh warmer can invalidate it in
# lockstep with the Redis key it already deletes -- see that module.
forecast_local_cache: TTLCache[ForecastResponse] = TTLCache(maxsize=64)


def _inverse_target(scaler, values: np.ndarray, region: str | None = None) -> np.ndarray:
    """`scaler` is a per-region `dict[str, StandardScaler]` for any
    version trained after `ml/train.py`'s per-region target-scaling fix
    (2026-08-15) -- `region` picks that region's own scaler. Still
    accepts a bare `StandardScaler` (the pre-fix shape) so an
    already-registered older version keeps serving correctly."""
    if isinstance(scaler, dict):
        if region is None:
            raise ValueError("per-region target_scaler requires `region`")
        scaler = scaler[region]
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
    # Every other region this bundle was trained on, fetched alongside
    # `region` -- so `build_features`'s cross-region-context features
    # reflect the real multi-region total the model was actually trained
    # against, not "region vs. itself" (see `load_latest_window`'s own
    # docstring for the real train/serve skew this fixes).
    cross_regions = [r for r in bundle.feature_scalers if r != region]
    raw_df = await load_latest_window(db, region, n_rows, cross_regions=cross_regions)
    own_rows = int((raw_df["region"] == region).sum())
    if own_rows < n_rows:
        raise ApiError(
            503,
            "insufficient_data",
            f"Not enough recent warehouse data for region '{region}' to build a forecast "
            f"(need {n_rows} rows, have {own_rows})",
        )

    holidays = await load_holidays(db)
    engineered = build_features(raw_df, holidays=holidays)
    window = engineered[engineered["region"] == region].tail(bundle.lookback)

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

    p10 = _inverse_target(bundle.target_scaler, out.p10.numpy(), region=region)
    p50 = _inverse_target(bundle.target_scaler, out.p50.numpy(), region=region)
    p90 = _inverse_target(bundle.target_scaler, out.p90.numpy(), region=region)
    # Real per-region P50 bias correction (`TODO.md` Phase 3), applied
    # before conformal calibration widens the band -- same bias-then-
    # conformal ordering `ml/train.py::train_model` fit the calibration
    # against, so serving matches how it was actually calibrated.
    # `region == "NEM"` gets no correction (no `"NEM"` key in
    # `bias_by_region` -- `.apply` is then a no-op), same as the
    # adaptive-scale exclusion below: an aggregate of 5 regions summed
    # together isn't what any single region's bias offset was fit for.
    p10, p50, p90 = bundle.bias_correction.apply(region, p10, p50, p90)
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


# Same real constraint `_run_baseline_fallback_forecast` above documents
# for its own history pool, times 2 for headroom -- the largest real
# `days` this endpoint accepts (30) at hourly cadence is 720 rows, well
# under this.
_RECENT_BACKTEST_MAX_DAYS = 30


async def _run_recent_backtest_single_region(
    db: AsyncSession, bundle: ModelBundle, region: str, days_back: int
) -> list[RecentBacktestPoint]:
    """Real walk-forward re-forecast of the currently-served model
    against `region`'s own real recent history -- same cross-region
    feature-context fetch `_run_inference` (the live-forecast path)
    already uses, so this scores the model under the same real feature
    conditions it's actually served under, not a simplified stand-in."""
    cross_regions = [r for r in bundle.feature_scalers if r != region]
    hours_needed = days_back * 24 + bundle.horizon
    n_rows = bundle.lookback + _FEATURE_WARMUP_ROWS + hours_needed
    raw_df = await load_latest_window(db, region, n_rows, cross_regions=cross_regions)
    own_rows = int((raw_df["region"] == region).sum())
    if own_rows < bundle.lookback + _FEATURE_WARMUP_ROWS + bundle.horizon + 1:
        # Not enough real history yet for even one scored origin -- a
        # real, expected state for a newly-onboarded region (same
        # "empty is a real state, not an error" convention `GET .../
        # evaluation` etc. already follow), not raised as a 503 here
        # since the caller (NEM aggregate or single-region response)
        # can still return a real (if short/empty) `points: []`.
        return []

    holidays = await load_holidays(db)
    engineered = build_features(raw_df, holidays=holidays)
    region_df = engineered[engineered["region"] == region].reset_index(drop=True)

    forecaster = LSTMForecaster(
        model=bundle.model,
        feature_scalers=bundle.feature_scalers,
        target_scaler=bundle.target_scaler,
        lookback=bundle.lookback,
        calibration=bundle.calibration,
        bias_correction=bundle.bias_correction,
    )
    return evaluate_recent_actual_vs_predicted(
        forecaster, region_df, bundle.horizon, days_back=days_back
    )


async def _run_recent_backtest_nem(
    db: AsyncSession, bundle: ModelBundle, days_back: int
) -> list[RecentBacktestPoint]:
    """Sums the 5 NEM regions' own real recent backtests point-for-point
    -- same "same 5-min AEMO dispatch clock" real assumption
    `_forecast_arrays_nem` above already relies on for the live forecast,
    just aligned by real `ts` (not array index) since each region's own
    walk-forward can land slightly different real gaps. A timestamp only
    becomes a real NEM total once all 5 regions actually scored a real
    point for it -- a partial 4-of-5 sum would silently understate the
    real total rather than honestly showing nothing for that step.
    """
    per_region = {
        region: await _run_recent_backtest_single_region(db, bundle, region, days_back)
        for region in _NEM_AGGREGATE_REGIONS
    }

    by_ts: dict[pd.Timestamp, list[RecentBacktestPoint]] = {}
    for pts in per_region.values():
        for p in pts:
            by_ts.setdefault(p.ts, []).append(p)

    merged: list[RecentBacktestPoint] = []
    for ts in sorted(by_ts):
        group = by_ts[ts]
        if len(group) != len(_NEM_AGGREGATE_REGIONS):
            continue
        actuals = [g.actual for g in group]
        merged.append(
            RecentBacktestPoint(
                ts=ts,
                actual=None if any(a is None for a in actuals) else sum(actuals),
                p10=sum(g.p10 for g in group),
                p50=sum(g.p50 for g in group),
                p90=sum(g.p90 for g in group),
                # Real, from whichever region's own walk-forward produced
                # this ts (they usually agree -- same shared clock -- but
                # aren't guaranteed to if two regions' real gaps caused
                # their own origin selection to diverge slightly; taking
                # the first is a real value either way, never invented).
                step_hours=group[0].step_hours,
            )
        )
    return merged


def recent_backtest_cache_key(region: str, days: int, model_version: str) -> str:
    """Shared with `app.service.cache_warmer` so the warmer writes to the
    exact key this route reads from -- same convention `model_drift_
    cache_key` (`app/api/v1/model/routes.py`) already establishes."""
    return f"forecast:recent_backtest:v1:{region}:{days}:{model_version}"


@router.get(
    "/forecast/recent-actual-vs-predicted", response_model=RecentBacktestResponse
)
async def get_recent_actual_vs_predicted(
    region: str,
    days: int = Query(default=7, ge=1, le=_RECENT_BACKTEST_MAX_DAYS),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    registry: ModelRegistry = Depends(get_model_registry),
    settings: Settings = Depends(get_app_settings),
) -> RecentBacktestResponse:
    """Real walk-forward re-forecast of the currently-served Production
    model against real actual demand for roughly the last `days` days,
    ending at the most recent real origin the warehouse has (see
    `service/ml/evaluate.py`'s `evaluate_recent_actual_vs_predicted` for
    the full reasoning).

    Redis-cached (`recent_backtest_cache_ttl_seconds`, 2026-08-11) --
    previously recomputed from real history on every single request,
    confirmed slow (`region=NEM` alone sums 5 independent per-region
    re-forecasts server-side; `lib/emissions.ts`'s `fetchRecentBacktest`
    uses a 45s timeout instead of every other call's 15s default because
    of it). Keyed on the currently-served model's own version, same as
    `GET /v1/forecast`'s cache -- a promotion/rollback invalidates this
    the same real way, not by waiting out a stale TTL.

    `region="NEM", days=30` specifically is also kept warm in the
    background (`cache_warmer.run_recent_backtest_warmer`) -- confirmed
    live 2026-08-11, this got *more* expensive as real history has
    grown (~158s now, not the ~50s measured when this cache was first
    added), so a live request landing on a cold cache is no longer an
    acceptable "occasionally slow" tail, it's a guaranteed timeout.
    "Emission History"'s forecast confidence band (`services/dashboard`)
    depends on this staying warm to honestly cover its full real 30-day
    period, not just a narrower recent slice.
    """
    bundle = registry.bundle
    if bundle is None:
        raise ApiError(
            503, "model_not_loaded", "No Production model version is loaded yet"
        )

    cache_key = recent_backtest_cache_key(region, days, bundle.version)
    cached = await redis.get(cache_key)
    if cached is not None:
        return RecentBacktestResponse.model_validate_json(cached)

    if region == "NEM":
        points = await _run_recent_backtest_nem(db, bundle, days)
    elif region in bundle.feature_scalers:
        points = await _run_recent_backtest_single_region(db, bundle, region, days)
    else:
        raise ApiError(
            503,
            "model_not_trained_for_region",
            f"The currently-served model has no fitted feature scaler for region '{region}' "
            "(it wasn't trained on this region)",
        )

    response = RecentBacktestResponse(
        region=region,
        model=f"{settings.mlflow_registry_model_name}@{bundle.stage.lower()}",
        generated_at=datetime.now(UTC),
        horizon_hours=bundle.horizon,
        interval="1h",
        days_requested=days,
        points=[
            RecentBacktestPointOut(
                ts=pd.Timestamp(p.ts).to_pydatetime(),
                actual=p.actual,
                p10=round(p.p10, 1),
                p50=round(p.p50, 1),
                p90=round(p.p90, 1),
                step_hours=p.step_hours,
            )
            for p in points
        ],
    )
    await redis.set(
        cache_key,
        response.model_dump_json(),
        ex=settings.recent_backtest_cache_ttl_seconds,
    )
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
        local_hit = forecast_local_cache.get(cache_key)
        if local_hit is not None:
            forecast_predictions_total.labels(region=region, cache="hit_local").inc()
            return local_hit

        cached = await redis.get(cache_key)
        if cached is not None:
            response = ForecastResponse.model_validate_json(cached)
            forecast_local_cache.set(cache_key, response, settings.forecast_cache_ttl_seconds)
            forecast_predictions_total.labels(region=region, cache="hit").inc()
            return response

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
        forecast_local_cache.set(cache_key, response, settings.forecast_cache_ttl_seconds)
        forecast_predictions_total.labels(region=region, cache="miss").inc()
        return response
