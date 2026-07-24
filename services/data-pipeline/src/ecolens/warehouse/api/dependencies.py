"""FastAPI dependency wrappers.

Pool/cache/settings live on `request.app.state` (wired up by
`app.py`'s lifespan) rather than module-level globals — that keeps
this importable and testable without a running app, and lets tests
swap in a fake pool via `app.dependency_overrides`.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, Query, Request

from .db import ConnectionPool
from .settings import WarehouseApiSettings
from .validation import validate_range, validate_region, validate_year


def require_api_key(
    request: Request,
    key: str | None = Query(default=None, alias="api_key"),
) -> None:
    settings: WarehouseApiSettings = request.app.state.settings
    if not settings.api_key:
        return
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid API key")


def require_pool(request: Request) -> ConnectionPool:
    """Dependency that returns 503 if the DB pool isn't ready."""
    pool: ConnectionPool | None = getattr(request.app.state, "pool", None)
    if pool is None or not pool.is_connected:
        raise HTTPException(
            status_code=503, detail="warehouse database unavailable; check /health"
        )
    return pool


def validate_region_dep(request: Request, region: str) -> str:
    """Dependency: 400 if region is unknown (runs BEFORE the pool check)."""
    validate_region(region, request.app.state.settings)
    return region


def validate_range_dep(since: datetime, until: datetime) -> tuple[datetime, datetime]:
    """Dependency: 400 if range is invalid (runs BEFORE the pool check)."""
    validate_range(since, until)
    return since, until


def validate_year_dep(year: int) -> int:
    """Dependency: 400 if year is out of range (runs BEFORE the pool check)."""
    validate_year(year)
    return year


__all__ = [
    "require_api_key",
    "require_pool",
    "validate_region_dep",
    "validate_range_dep",
    "validate_year_dep",
]
