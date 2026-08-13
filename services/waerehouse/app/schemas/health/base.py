from __future__ import annotations

from app.schemas.base import AppBaseModel


class ComponentHealth(AppBaseModel):
    name: str
    healthy: bool
    detail: str | None = None
