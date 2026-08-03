from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel


class ForecastPoint(AppBaseModel):
    ts: datetime
    p10: float
    p50: float
    p90: float
    unit: str = "MW"


class ForecastResponse(AppBaseModel):
    region: str
    model: str
    generated_at: datetime
    horizon: str
    interval: str
    points: list[ForecastPoint]
