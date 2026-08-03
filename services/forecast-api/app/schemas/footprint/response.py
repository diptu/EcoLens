from __future__ import annotations

from typing import Literal

from app.schemas.base import AppBaseModel


class FootprintResponse(AppBaseModel):
    region: str
    kwh: float
    kg_co2e: float
    intensity_kg_co2e_per_kwh: float
    method: Literal["live_mix_weighted"] = "live_mix_weighted"
    factors_version: str | None = None
