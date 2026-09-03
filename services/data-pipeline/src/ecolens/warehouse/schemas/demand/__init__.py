"""`DemandRow`/`DemandSummary` — per-region demand timeseries + summary,
read from `fact_demand_30min`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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


__all__ = ["DemandRow", "DemandSummary"]
