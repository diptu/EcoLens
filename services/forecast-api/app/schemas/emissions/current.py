from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class EmissionsCurrentResponse(AppBaseModel):
    """Backs `GET /v1/emissions/current` — each region's own most recent
    hour, summed. See `service/ml/data.py`'s `load_current_intensity`
    for why this isn't the same as "the single latest hour across all
    regions"."""

    as_of: datetime
    total_generation_mwh: float | None = None
    total_emissions_kgco2e: float | None = None
    intensity_kgco2e_per_mwh: float | None = None
    factors_version: str | None = None
    # `todo-model-training.md` Phase 7: real, not hardcoded -- see
    # `EmissionsResponse.method`'s identical comment.
    method: Literal["live_provider", "live_mix_weighted"] = "live_mix_weighted"
