from __future__ import annotations

from typing import Literal

from app.schemas.base import AppBaseModel


class HealthResponse(AppBaseModel):
    status: Literal["ok"] = "ok"


class ReadyComponent(AppBaseModel):
    ok: bool
    detail: str | None = None


class ReadyResponse(AppBaseModel):
    ready: bool
    database: ReadyComponent
    redis: ReadyComponent
    model: ReadyComponent
