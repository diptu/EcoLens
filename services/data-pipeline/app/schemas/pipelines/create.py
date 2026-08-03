from __future__ import annotations

from app.schemas.base import AppBaseModel

# ── 2.7/2.8 POST /v1/ingestion/{id}/{pause,resume} ───────────────────────


class PauseRequest(AppBaseModel):
    reason: str | None = None
