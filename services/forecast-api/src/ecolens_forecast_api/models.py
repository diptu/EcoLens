"""Pydantic response models for forecast-api."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ForecastStep(BaseModel):
    ts: datetime
    horizon_step: int
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None


class ForecastResponse(BaseModel):
    region: str
    generated_at: datetime
    as_of: datetime
    model: str
    interval_minutes: int
    steps: list[ForecastStep]


class HealthResponse(BaseModel):
    status: str
    pg: dict[str, Any]
    cache: dict[str, Any]
    model: dict[str, Any]
    uptime_seconds: float


__all__ = ["ForecastStep", "ForecastResponse", "HealthResponse"]
