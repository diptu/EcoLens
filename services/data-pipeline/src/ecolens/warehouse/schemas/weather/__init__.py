"""`WeatherRow` — per-region weather observations, joined onto
`fact_demand_30min`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class WeatherRow(BaseModel):
    ts: datetime
    region: str
    temp_c: float | None = None
    apparent_temp_c: float | None = None
    humidity_pct: float | None = None
    wind_speed_kmh: float | None = None
    wind_direction_deg: float | None = None
    wind_gust_kmh: float | None = None
    pressure_hpa: float | None = None
    rain_since_9am_mm: float | None = None


__all__ = ["WeatherRow"]
