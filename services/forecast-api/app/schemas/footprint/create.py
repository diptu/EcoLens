from __future__ import annotations

from app.schemas.base import AppBaseModel


class FootprintRequest(AppBaseModel):
    region: str
    kwh: float
    period: (
        str  # ISO 8601 interval, "start/end" (README.md's `POST /v1/footprint` example)
    )
