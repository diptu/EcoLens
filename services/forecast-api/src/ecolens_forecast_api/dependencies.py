"""FastAPI dependency wrappers.

Pool/cache/settings live on `request.app.state` (wired up by
`app.py`'s lifespan) rather than module-level globals, so this stays
importable/testable without a running app and tests can swap in a
fake pool via `app.dependency_overrides`.
"""

from __future__ import annotations

from fastapi import HTTPException, Query, Request

from .db import ConnectionPool
from .settings import ForecastApiSettings
from .validation import validate_region


def require_api_key(
    request: Request,
    key: str | None = Query(default=None, alias="api_key"),
) -> None:
    settings: ForecastApiSettings = request.app.state.settings
    if not settings.api_key:
        return
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid API key")


def require_pool(request: Request) -> ConnectionPool:
    """Dependency that returns 503 if the DB pool isn't ready."""
    pool: ConnectionPool | None = getattr(request.app.state, "pool", None)
    if pool is None or not pool.is_connected:
        raise HTTPException(
            status_code=503, detail="forecast database unavailable; check /health"
        )
    return pool


def validate_region_dep(request: Request, region: str) -> str:
    """Dependency: 400 if region is unknown (runs BEFORE the pool check)."""
    validate_region(region, request.app.state.settings)
    return region


__all__ = ["require_api_key", "require_pool", "validate_region_dep"]
