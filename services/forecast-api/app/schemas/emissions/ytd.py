from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class EmissionsYtdResponse(AppBaseModel):
    """Backs `GET /v1/emissions/ytd` — all-region rollup from the start
    of the current calendar year (UTC) to now, same
    `total_emissions_kgco2e`/`total_generation_mwh` shape as
    `EmissionsResponse` so a client already parsing that response
    can parse this one too."""

    since: datetime
    until: datetime
    total_generation_mwh: float | None = None
    total_emissions_kgco2e: float | None = None
    total_emissions_tco2e: float | None = None
    intensity_kgco2e_per_mwh: float | None = None
    factors_version: str | None = None
    method: Literal["live_mix_weighted"] = "live_mix_weighted"
