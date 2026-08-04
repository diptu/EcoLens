from __future__ import annotations

from typing import Literal

from app.schemas.base import AppBaseModel


class PromoteModelRequest(AppBaseModel):
    """`POST /v1/model/versions/{version}/promote`'s body."""

    stage: Literal["Production", "Staging", "Archived"]
