"""Request-parameter validation shared by dependencies.py and routes.py.

Pure functions — no I/O, no FastAPI `Depends` wiring here (see
`dependencies.py` for that). Kept separate so `/features/*` routes,
which validate region/range manually instead of via `Depends`, don't
have to import the dependency-injection wrappers just to reuse the
same checks.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException

from .settings import WarehouseApiSettings


def validate_region(region: str, settings: WarehouseApiSettings) -> None:
    if region not in settings.valid_regions:
        raise HTTPException(
            status_code=400,
            detail=f"invalid region {region!r}; valid: {', '.join(settings.valid_regions)}",
        )


def validate_range(since: datetime, until: datetime) -> None:
    if until <= since:
        raise HTTPException(status_code=400, detail="`until` must be after `since`")
    if (until - since) > timedelta(days=366):
        raise HTTPException(
            status_code=400,
            detail="range cannot exceed 1 year (use pagination for longer)",
        )


def validate_year(year: int) -> None:
    if year < 2000 or year > 2100:
        raise HTTPException(status_code=400, detail="year out of range")


__all__ = ["validate_region", "validate_range", "validate_year"]
