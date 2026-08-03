"""Schemas for /v1/forecast (ECO-D44). Shape mirrors README's example response."""

from __future__ import annotations

from app.schemas.forecast.create import ForecastRequest
from app.schemas.forecast.response import ForecastPoint, ForecastResponse

__all__ = ["ForecastPoint", "ForecastRequest", "ForecastResponse"]
