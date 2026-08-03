from __future__ import annotations

from app.schemas.base import AppBaseModel


class TokenRequest(AppBaseModel):
    username: str
    password: str
