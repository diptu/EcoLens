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
from app.schemas.forecast import ForecastPoint, ForecastResponse
from app.core.config import Settings
from app.service.ml.data import load_holidays, load_latest_window
from app.service.ml.features import (
    FEATURE_COLUMNS,
    NUMERIC_COLUMNS,
    build_features,
)
from app.models.ml import DemandForecast
from app.service.ml.registry import ModelBundle, ModelRegistry

router = APIRouter(prefix="/v1", tags=["forecast"])

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
    db: AsyncSession, bundle: ModelBundle, settings: Settings, region: str
) -> ForecastResponse:
    lo, p50, hi, step, last_ts = await _forecast_arrays_single_region(
        db, bundle, region
    )
    return _build_response(region, settings, bundle, lo, p50, hi, step, last_ts)


async def _run_nem_aggregate_forecast(
    db: AsyncSession, bundle: ModelBundle, settings: Settings
) -> ForecastResponse:
    lo, p50, hi, step, last_ts = await _forecast_arrays_nem(db, bundle)
    return _build_response("NEM", settings, bundle, lo, p50, hi, step, last_ts)


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

    cache_key = f"forecast:v1:{region}:{bundle.version}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return ForecastResponse.model_validate_json(cached)

    if region == "NEM":
        response = await _run_nem_aggregate_forecast(db, bundle, settings)
    else:
        response = await _run_single_region_forecast(db, bundle, settings, region)

    await redis.set(
        cache_key, response.model_dump_json(), ex=settings.forecast_cache_ttl_seconds
    )
    return response
