"""Response shapes for `POST /v1/features/rebuild`/`GET /v1/features/rebuild/runs`
-- real `meta._feature_selection_log` rows, root `TODO.md`'s "System
Commands" Rebuild Features item. Same shape/reasoning as `services/
waerehouse`'s `DbtBuildRunOut`/`DbtBuildRunsListResponse`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from app.schemas.base import AppBaseModel


class FeatureRebuildRunOut(AppBaseModel):
    """One `meta._feature_selection_log` row."""

    id: str
    triggered_by: str
    status: Literal["running", "success", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    n_selected: int | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class FeatureRebuildRunsListResponse(AppBaseModel):
    data: list[FeatureRebuildRunOut]


class FeatureRebuildTriggerResponse(AppBaseModel):
    run_id: str
    status: Literal["success"]
    n_selected: int
