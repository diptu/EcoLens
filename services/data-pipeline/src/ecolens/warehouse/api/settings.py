"""Warehouse-API-specific settings.

Why a separate file?
    Same rationale as `ecolens.ingestion.storage.settings.MongoSettings`:
    this is a distinct read surface (its own Postgres pool sizing, Redis
    cache TTL, port, row limits) with tuning that shouldn't couple to the
    rest of the data-pipeline service or to the ingestion layer's own
    Postgres/Redis usage.

The `db.py` / `cache.py` modules read from these settings. Override any
field via environment variables (e.g. `WAREHOUSE_PG_HOST`,
`WAREHOUSE_REDIS_URL`).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WarehouseApiSettings(BaseSettings):
    """Connection + tuning config for the read-only warehouse API."""

    model_config = SettingsConfigDict(
        env_prefix="warehouse_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── PostgreSQL ──────────────────────────────────────────────────────
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "ecolens_warehouse"
    pg_user: str = "ecolens"
    pg_password: str = "changeme"
    # Full asyncpg/libpq DSN (e.g. a Neon connection string:
    # postgresql://user:pass@ep-xxx.neon.tech/ecolens_warehouse?sslmode=require).
    # Takes over the connection entirely when set -- pg_host/port/database/
    # user/password above are ignored -- since managed providers like Neon
    # need sslmode=require, which the discrete pg_* fields have no slot for.
    # Unset (the default) keeps the plain local-Postgres path working.
    pg_dsn: str | None = Field(default=None)
    pg_min_pool: int = Field(default=2, ge=1, le=100)
    pg_max_pool: int = Field(default=10, ge=1, le=100)
    pg_command_timeout_seconds: float = 30.0

    # ── Redis (optional cache layer) ─────────────────────────────────────
    redis_url: str | None = Field(
        default=None,
        description="e.g. redis://localhost:6379/0. Cache is disabled if unset.",
    )
    cache_ttl_seconds: int = 60

    # ── API ───────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"  # nosec B104 - must bind all interfaces inside the container
    api_port: int = 8002
    api_key: str | None = Field(
        default=None,
        description="If set, require a matching X-API-Key/api_key on every request.",
    )
    default_max_rows: int = 10_000
    max_rows_limit: int = 100_000

    # Valid NEM/WEM regions
    valid_regions: tuple[str, ...] = ("NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM")


@lru_cache(maxsize=1)
def get_warehouse_api_settings() -> WarehouseApiSettings:
    """Cached settings singleton. Same pattern as `ecolens.config.get_settings()`."""
    return WarehouseApiSettings()


__all__ = ["WarehouseApiSettings", "get_warehouse_api_settings"]
