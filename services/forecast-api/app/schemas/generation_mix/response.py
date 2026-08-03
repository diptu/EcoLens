from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class GenerationMixItem(AppBaseModel):
    fuel_type: str
    category: Literal["renewable", "fossil", "storage", "interconnector"]
    is_renewable: bool
    total_generation_mwh: float
    total_emissions_kgco2e: float
    pct_of_total_generation: float


class GenerationMixResponse(AppBaseModel):
    """Backs `GET /v1/generation-mix` — per-fuel generation + emissions
    over a period, from `raw_marts.fct_generation_mix`. `region=None`
    (omitted query param) means all regions combined."""

    since: datetime
    until: datetime
    region: str | None = None
    total_generation_mwh: float
    total_emissions_kgco2e: float
    items: list[GenerationMixItem]
