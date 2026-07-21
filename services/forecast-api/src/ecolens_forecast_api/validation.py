"""Request-parameter validation. Pure functions, no I/O."""

from __future__ import annotations

from fastapi import HTTPException

from .settings import ForecastApiSettings


def validate_region(region: str, settings: ForecastApiSettings) -> None:
    if region not in settings.valid_regions:
        raise HTTPException(
            status_code=400,
            detail=f"invalid region {region!r}; valid: {', '.join(settings.valid_regions)}",
        )


def validate_horizon(horizon: int, settings: ForecastApiSettings) -> None:
    if horizon < 1 or horizon > settings.max_horizon_slots:
        raise HTTPException(
            status_code=400,
            detail=f"horizon must be between 1 and {settings.max_horizon_slots} "
            "(the baseline forecaster's lag depth)",
        )


__all__ = ["validate_region", "validate_horizon"]
