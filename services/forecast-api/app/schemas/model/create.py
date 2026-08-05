from __future__ import annotations

from typing import Literal

from app.schemas.base import AppBaseModel


class PromoteModelRequest(AppBaseModel):
    """`POST /v1/model/versions/{version}/promote`'s body. `model_name`
    (`todo-model-training.md` Phase 8) is optional -- `None` (the
    default) promotes a version of `Settings.mlflow_registry_model_name`
    (`lstm_demand`, unchanged existing behavior); pass e.g.
    `lstm_demand_tft` to promote a TFT version instead, now that more
    than one architecture is really registered."""

    stage: Literal["Production", "Staging", "Archived"]
    model_name: str | None = None
