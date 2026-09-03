"""`HealthResponse`/`ErrorResponse` — ops-facing response shapes, not
tied to any one warehouse table.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    pg: dict[str, Any]
    cache: dict[str, Any]
    uptime_seconds: float


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


__all__ = ["HealthResponse", "ErrorResponse"]
