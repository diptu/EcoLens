from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class ModelInfo(AppBaseModel):
    status: Literal["loaded", "not_loaded"]
    name: str
    version: str | None = None
    stage: str | None = None
    run_id: str | None = None
    loaded_at: datetime | None = None
    git_sha: str | None = None
    horizon: int | None = None
    lookback: int | None = None
    metrics: dict[str, float] = {}
