from __future__ import annotations

from app.schemas.base import AppBaseModel


class DbtRunResponse(AppBaseModel):
    subcommand: str
    target: str
    exit_code: int
