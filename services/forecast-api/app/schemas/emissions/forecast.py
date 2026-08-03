from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class EmissionsForecastPoint(AppBaseModel):
    ts: datetime
    p10_kgco2e: float
    p50_kgco2e: float
    p90_kgco2e: float


class EmissionsForecastResponse(AppBaseModel):
    """Backs `GET /v1/emissions/forecast` — a projected emissions band,
    derived as `GET /v1/forecast`'s demand P10/P50/P90 (MW) x each
    forecast step's duration x the region's *current* carbon intensity
    (kgCO2e/MWh), held constant across the horizon. This is a real,
    if approximate, methodology (current intensity applied forward) —
    not a learned emissions-forecasting model. See
    `api/v1/emissions/routes.py`'s `get_emissions_forecast` docstring."""

    region: str
    generated_at: datetime
    horizon: str
    interval: str
    intensity_kgco2e_per_mwh: float
    factors_version: str | None = None
    points: list[EmissionsForecastPoint]
    method: Literal["demand_forecast_x_current_intensity"] = (
        "demand_forecast_x_current_intensity"
    )
