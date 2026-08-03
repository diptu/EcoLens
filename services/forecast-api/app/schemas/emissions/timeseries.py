from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class EmissionsTimeseriesPoint(AppBaseModel):
    bucket: datetime
    total_generation_mwh: float | None = None
    total_emissions_kgco2e: float | None = None
    intensity_kgco2e_per_mwh: float | None = None


class EmissionsTimeseriesResponse(AppBaseModel):
    """Backs `GET /v1/emissions/timeseries` — actual emissions bucketed
    by hour or day, over `raw_marts.fct_carbon_intensity`. `region=None`
    (the default) aggregates across all regions; otherwise filtered to
    just that one, same optional-region convention `GET /v1/generation-mix`
    already uses."""

    since: datetime
    until: datetime
    bucket: Literal["hour", "day"]
    region: str | None = None
    factors_version: str | None = None
    points: list[EmissionsTimeseriesPoint]
