from __future__ import annotations

from typing import Literal

from app.schemas.base import AppBaseModel
from app.schemas.health.base import ComponentHealth


class HealthResponse(AppBaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(AppBaseModel):
    status: Literal["ready", "not_ready"]
    components: list[ComponentHealth]
