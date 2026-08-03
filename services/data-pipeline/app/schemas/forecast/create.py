from __future__ import annotations

from app.schemas.base import AppBaseModel


class ForecastRequest(AppBaseModel):
    region: str
    horizon: str = "24h"
    interval: str = "30m"
