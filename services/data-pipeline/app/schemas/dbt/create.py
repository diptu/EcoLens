from __future__ import annotations

from app.schemas.base import AppBaseModel


class DbtRunRequest(AppBaseModel):
    target: str | None = None
    extra_args: list[str] = []
