from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class ForecastPoint(AppBaseModel):
    ts: datetime
    p10: float
    p50: float
    p90: float
    unit: Literal["MW"] = "MW"


class ForecastResponse(AppBaseModel):
    """`horizon`/`interval` report the model's *actual* native output
    cadence (e.g. `"4h"`/`"5m"` for a source trained on 5-min NEM data),
    not whatever a caller requested via those query params — v0 doesn't
    resample the model's output to an arbitrary requested interval/
    horizon (see `api/v1/forecast/routes.py`'s docstring); returning the
    true values here rather than echoing the request back is deliberate,
    so a caller can always tell what it actually got."""

    region: str
    model: str
    generated_at: datetime
    horizon: str
    interval: str
    points: list[ForecastPoint]
