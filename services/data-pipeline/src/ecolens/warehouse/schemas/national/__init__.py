"""National (all-region, or `/national/*`-scoped) summaries: real mass
emissions (`NationalSummary`), the daily emissions trend line
(`NationalDailyEmissionsRow`), and the grid generation mix
(`NationalGenerationMix`).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


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


__all__ = ["NationalSummary", "NationalDailyEmissionsRow", "NationalGenerationMix"]
