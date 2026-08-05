"""Shared Pydantic v2 base for the API's response/request schemas.
Ported verbatim from ingestion/data-pipeline's identical module."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AppBaseModel(BaseModel):
    """All API schemas inherit from this instead of `BaseModel` directly,
    so config (serialization, aliasing, ...) stays consistent in one place."""

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
