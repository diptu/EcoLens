"""`GET /v1/forecast/intelligence` -- the real multi-task demand +
generation-mix + carbon-intelligence endpoint (`todo-model-training.md`'s
originally-scoped approximation, now genuinely model-predicted --
see `app/schemas/forecast_intelligence/response.py`'s module docstring).

Serves at `EnergyForecastLSTM`'s native cadence (same "don't resample to
an arbitrary requested interval" choice `/v1/forecast` already makes --
see that module's own docstring for why), from the *second*,
independent `EnergyModelRegistry` (`main.py`'s lifespan) -- this route
never touches the single-task `lstm_demand` model or its registry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import torch
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_db, get_energy_model_registry, get_redis_client
from app.core.config import Settings
from app.core.errors import ApiError
from app.models.energy_forecast_lstm import P10, P50, P90
from app.schemas.forecast_intelligence import (
    ForecastIntelligenceMetadata,
    ForecastIntelligencePoint,
    ForecastIntelligenceResponse,
    QuantileValue,
)
from app.service.ml.carbon_engine import CarbonEngine
from app.service.ml.data import load_holidays
from app.service.ml.emission_factors import load_generation_bucket_factors
from app.service.ml.energy_data import load_latest_energy_window
from app.service.ml.energy_features import FEATURE_COLUMNS, build_features, warmup_rows_for_region
from app.service.ml.energy_registry import EnergyModelBundle, EnergyModelRegistry
from app.service.ml.reconciliation import reconcile_generation

router = APIRouter(prefix="/v1", tags=["forecast-intelligence"])

#: `GENERATION_TARGET_COLUMNS` order (`coal_mw`/`gas_mw`/`wind_mw`/
#: `solar_mw`/`other_mw`), stripped of the `_mw` suffix -- the response's
#: `generation_mix_breakdown_mw` keys and `EnergyForecast.generation`'s
#: source dim share this exact order; zip, don't re-derive.
_BUCKET_NAMES: tuple[str, ...] = ("coal", "gas", "wind", "solar", "other")
_RENEWABLE_BUCKETS = frozenset({"wind", "solar"})


def _infer_step(ts: pd.Series) -> timedelta:
    diffs = ts.diff().dropna()
    if diffs.empty:
        raise ApiError(503, "insufficient_data", "not enough recent rows to infer a time step")
    return pd.Timedelta(diffs.median()).to_pytimedelta()


def _format_timedelta(delta: timedelta) -> str:
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes % 60 == 0 and total_minutes >= 60:
        return f"{total_minutes // 60}h"
    return f"{total_minutes}m"


async def _run_energy_inference(
    db: AsyncSession, bundle: EnergyModelBundle, region: str
) -> tuple[torch.Tensor, torch.Tensor, pd.Series]:
    """Returns `(demand, generation, window_ts)` -- raw (unreconciled,
    still-scaled) model output, same "one forward pass, format later"
    split `/v1/forecast`'s `_run_inference` uses."""
    n_rows = bundle.lookback + warmup_rows_for_region(region)
    raw_df = await load_latest_energy_window(db, region, n_rows)
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
            f"The currently-served energy-forecast model has no fitted feature scaler for "
            f"region '{region}' (it wasn't trained on this region)",
        )

    # Unlike `/v1/forecast`'s route, `FEATURE_COLUMNS` here was scaled as
    # one uniform block at training time (`train_energy_forecast.
    # train_energy_model`'s `fit_scalers(..., columns=FEATURE_COLUMNS)`
    # -- no separate NUMERIC_COLUMNS subset) -- transform the whole
    # matrix through the one fitted scaler, not a subset of it.
    scaled = feature_scaler.transform(feature_matrix.to_numpy(dtype=np.float64))
    x = torch.tensor(scaled, dtype=torch.float32).unsqueeze(0)

    bundle.model.eval()
    with torch.no_grad():
        out = bundle.model(x)

    return out.demand, out.generation, window["ts"]


def _inverse(scaler, values: np.ndarray) -> np.ndarray:
    shape = values.shape
    return scaler.inverse_transform(values.reshape(-1, 1)).reshape(shape)


async def _build_response(
    db: AsyncSession, bundle: EnergyModelBundle, settings: Settings, region: str
) -> ForecastIntelligenceResponse:
    demand, generation, window_ts = await _run_energy_inference(db, bundle, region)

    # Inverse-transform to real MW *before* reconciling, not after.
    # `StandardScaler` is affine (subtracts a fitted mean), not a pure
    # multiplicative scale, and `demand_scaler`/`generation_scaler` have
    # different means/stds (fit independently) -- reconciling in scaled
    # space and inverse-transforming afterward gives a *different*,
    # wrong sum-to-demand result than reconciling in real MW space
    # directly (confirmed empirically while building this: a synthetic
    # case with real target sum 6000 MW came back 7500 MW reconciled in
    # scaled space vs. the correct 6000 MW reconciled in MW space).
    demand_mw_raw = _inverse(bundle.demand_scaler, demand.numpy())  # [1, H, 3]
    generation_mw_raw = _inverse(bundle.generation_scaler, generation.numpy())  # [1, H, S, 3]
    generation_mw = reconcile_generation(
        torch.from_numpy(demand_mw_raw), torch.from_numpy(generation_mw_raw)
    ).numpy()
    demand_mw = demand_mw_raw

    factors = await load_generation_bucket_factors(db)
    # Real query, but the model itself only ever emits `_BUCKET_NAMES`'
    # 5 buckets -- filter/order to exactly those, in that order, rather
    # than trusting whatever key order the DB query happened to return.
    engine = CarbonEngine(
        emission_factors={name: factors[name] for name in _BUCKET_NAMES},
        interval_hours=_infer_step(window_ts).total_seconds() / 3600.0,
    )
    carbon = engine.calculate(
        generation_mw=torch.from_numpy(generation_mw), demand_mw=torch.from_numpy(demand_mw)
    )
    emissions_kg = carbon["emissions_kg"].numpy()  # [1, H, 3]
    carbon_intensity = carbon["carbon_intensity"].numpy()  # [1, H, 3]

    step = _infer_step(window_ts)
    last_ts = window_ts.iloc[-1].to_pydatetime()
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=UTC)

    points = []
    for h in range(bundle.horizon):
        demand_q = QuantileValue(
            p10=round(float(demand_mw[0, h, P10]), 1),
            p50=round(float(demand_mw[0, h, P50]), 1),
            p90=round(float(demand_mw[0, h, P90]), 1),
        )
        mix = {
            name: QuantileValue(
                p10=round(float(generation_mw[0, h, i, P10]), 1),
                p50=round(float(generation_mw[0, h, i, P50]), 1),
                p90=round(float(generation_mw[0, h, i, P90]), 1),
            )
            for i, name in enumerate(_BUCKET_NAMES)
        }
        total_p50 = sum(mix[name].p50 for name in _BUCKET_NAMES)
        renewable_p50 = sum(mix[name].p50 for name in _RENEWABLE_BUCKETS)
        renewable_share = renewable_p50 / total_p50 if total_p50 > 0 else 0.0

        points.append(
            ForecastIntelligencePoint(
                ts=last_ts + step * (h + 1),
                electricity_demand_mw=demand_q,
                generation_mix_breakdown_mw=mix,
                emissions_kg=QuantileValue(
                    p10=round(float(emissions_kg[0, h, P10]), 2),
                    p50=round(float(emissions_kg[0, h, P50]), 2),
                    p90=round(float(emissions_kg[0, h, P90]), 2),
                ),
                carbon_intensity_gco2e_per_kwh=QuantileValue(
                    p10=round(float(carbon_intensity[0, h, P10]), 1),
                    p50=round(float(carbon_intensity[0, h, P50]), 1),
                    p90=round(float(carbon_intensity[0, h, P90]), 1),
                ),
                renewable_proportion_derived=round(renewable_share, 4),
            )
        )

    return ForecastIntelligenceResponse(
        region=region,
        model=f"{settings.energy_forecast_model_name}@{bundle.stage.lower()}",
        generated_at=datetime.now(UTC),
        horizon=_format_timedelta(step * bundle.horizon),
        interval=_format_timedelta(step),
        metadata=ForecastIntelligenceMetadata(),
        points=points,
    )


@router.get("/forecast/intelligence", response_model=ForecastIntelligenceResponse)
async def get_forecast_intelligence(
    region: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    registry: EnergyModelRegistry = Depends(get_energy_model_registry),
    settings: Settings = Depends(get_app_settings),
) -> ForecastIntelligenceResponse:
    bundle = registry.bundle
    if bundle is None:
        raise ApiError(
            503,
            "energy_model_not_loaded",
            "No Production version of the multi-task energy-forecast model is loaded yet",
        )

    cache_key = f"forecast_intelligence:v1:{region}:{bundle.version}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return ForecastIntelligenceResponse.model_validate_json(cached)

    response = await _build_response(db, bundle, settings, region)

    await redis.set(cache_key, response.model_dump_json(), ex=settings.forecast_cache_ttl_seconds)
    return response
