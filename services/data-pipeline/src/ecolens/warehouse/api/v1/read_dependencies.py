"""FastAPI dependency wrappers.

Pool/cache/settings live on `request.app.state` (wired up by
`app.py`'s lifespan) rather than module-level globals — that keeps
this importable and testable without a running app, and lets tests
swap in a fake pool via `app.dependency_overrides`.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, Query, Request

from ecolens.warehouse.core.api_settings import WarehouseApiSettings
from ecolens.warehouse.core.periods import VALID_PERIODS
from ecolens.warehouse.core.regions import ANALYTICS_VALID_REGIONS
from ecolens.warehouse.core.validation import (
    validate_range,
    validate_region,
    validate_year,
)
from ecolens.warehouse.db.connection import ConnectionPool

VALID_CURRENCIES: tuple[str, ...] = ("AUD", "USD", "EUR")


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


# ── /api/analytics/executive-kpis ────────────────────────────────────────
# Error body shape deliberately matches every route above (plain
# `HTTPException(detail=...)`, `{"detail": "..."}`) rather than that
# endpoint's own spec, which describes a richer `{"error": {"code",
# ...}}` envelope -- forking a second error shape for one route would be
# a worse inconsistency than not matching that spec verbatim.


def validate_period_dep(period: str = Query(default="ytd")) -> str:
    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid value for 'period': {period!r}; must be one of "
            f"{', '.join(VALID_PERIODS)}",
        )
    return period


def validate_analytics_region_dep(region: str = Query(default="NEM")) -> str:
    if region not in ANALYTICS_VALID_REGIONS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid value for 'region': {region!r}; must be one of "
            f"{', '.join(ANALYTICS_VALID_REGIONS)}",
        )
    return region


def validate_currency_dep(currency: str = Query(default="AUD")) -> str:
    if currency not in VALID_CURRENCIES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid value for 'currency': {currency!r}; must be one of "
            f"{', '.join(VALID_CURRENCIES)}",
        )
    return currency


__all__ = [
    "require_api_key",
    "require_pool",
    "validate_region_dep",
    "validate_range_dep",
    "validate_year_dep",
    "VALID_CURRENCIES",
    "validate_period_dep",
    "validate_analytics_region_dep",
    "validate_currency_dep",
]
