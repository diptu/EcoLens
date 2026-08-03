from __future__ import annotations

from app.schemas.base import AppBaseModel


class PromotionResponse(AppBaseModel):
    model_name: str
    promoted: bool
    candidate_version: str
    candidate_mape: float
    production_mape: float | None = None
    reason: str
