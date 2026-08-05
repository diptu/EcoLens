from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class EmissionsResponse(AppBaseModel):
    region: str
    as_of: datetime
    intensity_kgco2e_per_mwh: float | None = None
    total_generation_mwh: float | None = None
    total_emissions_kgco2e: float | None = None
    factors_version: str | None = None
    # `todo-model-training.md` Phase 7: real, not hardcoded -- reports
    # which method actually served this response, decided per-request by
    # `service/ml/data.resolve_intensity_method`'s freshness check.
    method: Literal["live_provider", "live_mix_weighted"] = "live_mix_weighted"
