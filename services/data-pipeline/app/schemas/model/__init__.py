"""Schemas for `POST /v1/model/train` (Model Operations TODO.md Phase 2)."""

from __future__ import annotations

from app.schemas.model.create import TrainRequest
from app.schemas.model.response import (
    TrainingRunOut,
    TrainingRunsListResponse,
    TrainTriggerResponse,
)

__all__ = [
    "TrainRequest",
    "TrainingRunOut",
    "TrainingRunsListResponse",
    "TrainTriggerResponse",
]
