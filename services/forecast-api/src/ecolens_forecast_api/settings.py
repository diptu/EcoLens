"""forecast-api settings.

A separate `BaseSettings` from data-pipeline's `Settings` /
`WarehouseApiSettings` — same rationale as those two (see
`ingestion.storage.settings.MongoSettings`'s docstring in
data-pipeline): this is its own deployable with its own Postgres pool
sizing, cache TTL, and port, and shouldn't couple its tuning to
another service's.

Points at the same `ecolens_warehouse` Postgres database the warehouse
API reads (`ml_features_demand_v1` lives there) but never queries it
directly with a second connection surface's assumptions baked in.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ForecastApiSettings(BaseSettings):
    """Connection + tuning config for the forecast-serving API."""

    model_config = SettingsConfigDict(
        env_prefix="forecast_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── PostgreSQL (warehouse database — read-only) ──────────────────────
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "ecolens_warehouse"
    pg_user: str = "ecolens"
    pg_password: str = "changeme"
    pg_min_pool: int = Field(default=2, ge=1, le=100)
    pg_max_pool: int = Field(default=10, ge=1, le=100)
    pg_command_timeout_seconds: float = 30.0

    # ── Redis (optional cache layer) ─────────────────────────────────────
    redis_url: str | None = Field(
        default=None,
        description="e.g. redis://localhost:6379/0. Cache is disabled if unset.",
    )
    cache_ttl_seconds: int = 300

    # ── API ───────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"  # nosec B104 - must bind all interfaces inside the container
    api_port: int = 8003
    api_key: str | None = Field(
        default=None,
        description="If set, require a matching X-API-Key/api_key on every request.",
    )

    # Valid NEM/WEM regions (same set the warehouse mart is keyed on).
    valid_regions: tuple[str, ...] = ("NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM")

    # ── Forecast tunables ─────────────────────────────────────────────────
    # 30-min slots; 48 = 24h horizon. Matches data-pipeline Settings.model_horizon
    # and ml_features_demand_v1's lag depth -- the baseline forecaster can only
    # see as far as it has lag columns for.
    default_horizon_slots: int = 48
    max_horizon_slots: int = 48
    interval_minutes: int = 30
    # 80% interval (conformal_alpha=0.1 in data-pipeline's Settings), applied
    # naively via the mart's rolling stddev -- see baseline.py's docstring for
    # why this is not true conformal calibration.
    interval_z_score: float = 1.2816


@lru_cache(maxsize=1)
def get_forecast_api_settings() -> ForecastApiSettings:
    """Cached settings singleton. Same pattern as `ecolens.config.get_settings()`."""
    return ForecastApiSettings()


__all__ = ["ForecastApiSettings", "get_forecast_api_settings"]
