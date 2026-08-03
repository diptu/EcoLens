"""Schemas for `POST /v1/auth/token`."""

from __future__ import annotations

from app.schemas.auth.create import TokenRequest
from app.schemas.auth.response import TokenResponse

__all__ = ["TokenRequest", "TokenResponse"]
