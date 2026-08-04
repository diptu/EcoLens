from __future__ import annotations

from app.schemas.base import AppBaseModel


class TrainRequest(AppBaseModel):
    """`POST /v1/model/train`'s body -- both fields optional, defaulting
    to `Settings.model_default_regions`/`incremental_train_window_hours`,
    the same defaults the automatic (dbt-build-triggered) path falls
    back to."""

    regions: list[str] | None = None
    window_hours: int | None = None
