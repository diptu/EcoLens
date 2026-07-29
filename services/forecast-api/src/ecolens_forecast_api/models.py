"""Pydantic response models for forecast-api."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CarbonMetrics(BaseModel):
    """Root TODO.md's "Deterministic Carbon Accounting" block --
    computed straight from `source_breakdown_mw` by
    `forecasting/carbon.py`, never predicted by a model.
    """

    predicted_total_carbon_kgco2e: float
    emissions_intensity_kgco2e_per_mwh: float
    renewable_proportion: float


class WeatherContext(BaseModel):
    """Current conditions only, not a forecast -- root TODO.md's "API &
    Registry Serving" section is explicit that this block is for
    explainability ("why is demand/the source mix what it is right now"),
    not a weather forecast. One value per response (as-of the same row
    the point forecast itself was built from), not one per horizon step.
    """

    temp_c: float | None = None
    humidity_pct: float | None = None
    wind_speed_kmh: float | None = None


class ForecastStep(BaseModel):
    ts: datetime
    horizon_step: int
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    # None whenever the fuel ensemble isn't loaded (root TODO.md's
    # "API & Registry Serving": "Only the first block exists today" --
    # this is what closes that gap, gracefully degrading the same way an
    # unloaded LSTM already degrades total_demand_mw to the baseline
    # forecaster instead of erroring) -- see routes.py.
    source_breakdown_mw: dict[str, float] | None = None
    carbon_metrics: CarbonMetrics | None = None


class ForecastResponse(BaseModel):
    region: str
    generated_at: datetime
    as_of: datetime
    model: str
    interval_minutes: int
    steps: list[ForecastStep]
    weather_context: WeatherContext | None = None


class HealthResponse(BaseModel):
    status: str
    pg: dict[str, Any]
    cache: dict[str, Any]
    model: dict[str, Any]
    uptime_seconds: float


__all__ = [
    "ForecastStep",
    "ForecastResponse",
    "HealthResponse",
    "CarbonMetrics",
    "WeatherContext",
]
