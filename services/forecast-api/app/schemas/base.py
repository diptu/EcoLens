"""Shared Pydantic v2 base — same config as `data-pipeline`'s
`app.schemas.base` (intentionally duplicated, trivial)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AppBaseModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
