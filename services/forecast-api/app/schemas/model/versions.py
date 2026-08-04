"""`GET /v1/model/versions` (Model Operations TODO.md Phase 1) --
every registered MLflow version of the model, any stage -- distinct
from `ModelInfo` (`GET /v1/model`), which only ever reports whichever
one is currently `Production`."""

from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel


class ModelVersionOut(AppBaseModel):
    version: str
    stage: str
    run_id: str
    created_at: datetime
    metrics: dict[str, float] = {}
    git_sha: str | None = None


class ModelVersionsListResponse(AppBaseModel):
    name: str
    data: list[ModelVersionOut]
