"""`GenerationRow` — per-region fuel-mix timeseries, read from
`fact_generation_30min`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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


__all__ = ["GenerationRow"]
