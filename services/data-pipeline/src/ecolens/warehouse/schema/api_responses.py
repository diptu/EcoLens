"""Pydantic response models for the warehouse API.

Mirror the dbt marts described in `warehouse/werehouse.md`:
`dim_region`, `fact_demand_30min` (demand/generation/weather all read
from this one wide mart), `dim_holiday`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel


class Region(BaseModel):
    region: str
    state: str
    population: int | None = None
    timezone: str | None = None


class DemandRow(BaseModel):
    ts: datetime
    region: str
    demand_mw: float | None = None
    price_mwh: float | None = None
    renewable_proportion: float | None = None
    emissions_intensity_kgco2e_per_mwh: float | None = None
    temp_c: float | None = None
    humidity_pct: float | None = None
    is_holiday: int | None = None


class GenerationRow(BaseModel):
    ts: datetime
    region: str
    coal_black_mw: float | None = None
    coal_brown_mw: float | None = None
    gas_ccgt_mw: float | None = None
    gas_ocgt_mw: float | None = None
    wind_mw: float | None = None
    solar_utility_mw: float | None = None
    solar_rooftop_mw: float | None = None
    battery_discharge_mw: float | None = None
    hydro_mw: float | None = None
    biomass_mw: float | None = None
    total_generation_mw: float | None = None


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


class DemandSummary(BaseModel):
    region: str
    since: datetime
    until: datetime
    n_obs: int
    avg_demand_mw: float | None = None
    peak_demand_mw: float | None = None
    peak_ts: datetime | None = None
    min_demand_mw: float | None = None
    total_energy_mwh: float | None = None
    avg_price_mwh: float | None = None
    avg_renewable_proportion: float | None = None
    avg_temp_c: float | None = None


class NationalSummary(BaseModel):
    since: datetime
    until: datetime
    n_slots: int
    avg_demand_mw: float | None = None
    peak_demand_mw: float | None = None
    peak_ts: datetime | None = None
    min_demand_mw: float | None = None
    total_energy_mwh: float | None = None
    avg_renewable_proportion: float | None = None
    avg_emissions_intensity_kgco2e_per_mwh: float | None = None
    total_carbon_tco2e: float | None = None


class NationalDailyEmissionsRow(BaseModel):
    date_local: date
    total_demand_mwh: float | None = None
    avg_renewable_proportion: float | None = None
    avg_emissions_intensity_kgco2e_per_mwh: float | None = None
    total_carbon_tco2e: float | None = None


class NationalGenerationMix(BaseModel):
    since: datetime
    until: datetime
    total_mw: float
    mix_mw: dict[str, float]
    mix_share: dict[str, float]


class HolidayRow(BaseModel):
    date: date
    region: str
    state: str
    holiday_name: str
    holiday_type: str
    is_observed: bool = False
    days_until: int | None = None


class PaginatedHolidays(BaseModel):
    items: list[HolidayRow]
    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    status: str
    pg: dict[str, Any]
    cache: dict[str, Any]
    uptime_seconds: float


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


# ── /api/analytics/executive-kpis ────────────────────────────────────────
# Field names/shape follow that endpoint's spec exactly (`id`, `label`,
# `value`, `value_display`, `unit`, `delta_pct`, `trend`, `good_when`,
# `is_good`, `sub`, `sparkline`) so the Next.js BFF/dashboard can
# consume this without any field-renaming glue.

Trend = Literal["up", "down", "flat"]


class KpiCard(BaseModel):
    id: str
    label: str
    value: float | None = None
    value_display: str
    unit: str
    delta_pct: float | None = None
    trend: Trend
    good_when: Trend
    is_good: bool
    sub: str | None = None
    sparkline: list[float] = []


class PreviousPeriod(BaseModel):
    start: datetime
    end: datetime


class ExecutiveKpisMeta(BaseModel):
    period: str
    region: str
    currency: str
    as_of: datetime
    previous_period: PreviousPeriod
    generated_at: datetime


class ExecutiveKpisResponse(BaseModel):
    meta: ExecutiveKpisMeta
    kpis: list[KpiCard]


__all__ = [
    "Region",
    "DemandRow",
    "GenerationRow",
    "WeatherRow",
    "DemandSummary",
    "NationalSummary",
    "NationalDailyEmissionsRow",
    "NationalGenerationMix",
    "HolidayRow",
    "HealthResponse",
    "ErrorResponse",
    "Trend",
    "KpiCard",
    "PreviousPeriod",
    "ExecutiveKpisMeta",
    "ExecutiveKpisResponse",
]
