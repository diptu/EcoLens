from __future__ import annotations

from typing import Literal

from app.schemas.base import AppBaseModel


class TokenResponse(AppBaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    role: str
