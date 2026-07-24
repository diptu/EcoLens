"""Warehouse-runner-specific settings.

Why a separate file?
    Same rationale as `MongoSettings` / `WarehouseApiSettings`: this is
    a distinct surface (dbt invocation, source-freshness thresholds,
    quality thresholds, retention policy) with tuning that shouldn't
    couple to the rest of the data-pipeline service.

No MongoDB connection fields here on purpose: `SourceFreshnessChecker`
and `ArchiveManager` both take an optional `MongoSettings` instead of
duplicating `mongo_uri`/`mongo_db_name` on this class. A previous
version of this file *did* duplicate them (`WAREHOUSE_RUNNER_MONGO_URI`,
separate from the `MONGO_URI` env var ingestion actually reads) and it
was a real footgun: set `MONGO_URI` for ingestion, forget the
warehouse-runner-specific copy, and freshness/archive silently connect
to `localhost:27017` instead of the real cluster.

Defaults are chosen to work out of the box in this repo/dev machine
(the dbt project dir resolves to the real `warehouse/dbt_project/`
already in this tree; the log dir is CWD-relative) rather than the
container-only absolute paths (`/opt/ecolens/dbt`, `/var/log/ecolens`)
a production deployment would override via env vars.
"""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# services/data-pipeline/src/ecolens/warehouse/dbt_project/
_DEFAULT_DBT_PATH = Path(__file__).resolve().parent.parent / "dbt_project"


class WarehouseRunnerSettings(BaseSettings):
    """Connection + tuning config for the warehouse dbt runner."""

    model_config = SettingsConfigDict(
        env_prefix="warehouse_runner_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── PostgreSQL (warehouse) ───────────────────────────────────────────
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "ecolens_warehouse"
    pg_user: str = "ecolens"
    pg_password: str = "changeme"
    # Full asyncpg/libpq DSN (e.g. a Neon connection string:
    # postgresql://user:pass@ep-xxx.neon.tech/ecolens_warehouse?sslmode=require).
    # Takes over the connection entirely when set -- see
    # WarehouseApiSettings.pg_dsn's docstring for the full rationale.
    pg_dsn: str | None = Field(default=None)

    # ── dbt ───────────────────────────────────────────────────────────────
    dbt_path: Path = _DEFAULT_DBT_PATH  # directory with dbt_project.yml
    dbt_profiles_dir: Path = _DEFAULT_DBT_PATH  # profiles.yml lives here
    dbt_target: str = "prod"  # dev / staging / prod
    dbt_binary: str = "dbt"  # absolute path or "dbt" (resolved via PATH)
    dbt_threads: int = Field(default=1, ge=1, le=32)
    dbt_timeout_seconds: int = Field(default=600, ge=1)  # hard cap

    # ── Source freshness thresholds (fail if older than this) ────────────
    freshness_threshold_aemo: timedelta = timedelta(minutes=45)
    freshness_threshold_bom: timedelta = timedelta(hours=2)
    freshness_threshold_holidays: timedelta = timedelta(days=7)

    # ── Quality thresholds ────────────────────────────────────────────────
    max_null_pct: float = Field(default=0.10, ge=0.0, le=1.0)
    max_consecutive_gap_minutes: int = 90  # 1.5h gap in 30-min series = error

    # ── Retention ─────────────────────────────────────────────────────────
    archive_after_days: int = Field(default=365, ge=1)
    vacuum_after_hours: int = Field(default=24, ge=1)

    # ── Raw sync (MongoDB -> PostgreSQL raw.*, ecolens.ingestion.storage.postgres) ──
    raw_sync_lookback_days: int = Field(
        default=5,
        ge=1,
        description=(
            "Incremental raw-sync window in days (matches the dbt project's "
            "own `lookback_days` var -- both exist to catch late-arriving "
            "AEMO settlement data). Ignored on --full runs, which resync "
            "everything."
        ),
    )

    # ── Logging ───────────────────────────────────────────────────────────
    log_dir: Path = Path("data/log")
    metrics_enabled: bool = False  # toggle if Prometheus gets wired up later


@lru_cache(maxsize=1)
def get_warehouse_runner_settings() -> WarehouseRunnerSettings:
    """Cached settings singleton. Same pattern as `ecolens.config.get_settings()`."""
    return WarehouseRunnerSettings()


__all__ = ["WarehouseRunnerSettings", "get_warehouse_runner_settings"]
