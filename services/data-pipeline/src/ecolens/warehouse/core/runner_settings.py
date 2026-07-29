"""Warehouse-runner-specific settings.

Why a separate file?
    Same rationale as `IngestionSettings` / `WarehouseApiSettings`: this
    is a distinct surface (dbt invocation, source-freshness thresholds,
    quality thresholds) with tuning that shouldn't couple to the rest
    of the data-pipeline service.

No DuckDB path field here on purpose: `SourceFreshnessChecker` reads
`Settings.historical_duckdb_path` (the same path every other ingestion
write path uses), not a warehouse-runner-specific duplicate -- keeping
the DuckDB location single-sourced avoids the exact footgun a previous
version of this file had with a separate `WAREHOUSE_RUNNER_MONGO_URI`
env var drifting from the `MONGO_URI` ingestion actually read.

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
    # aemo_nem/aemo_wem (and openelectricity, which shares this threshold
    # -- see freshness.py's `sources` list) are gated by this Stage 1
    # check (SourceFreshnessChecker) *before* dbt even runs, unlike
    # quality.py's post-dbt FRESHNESS_CHECKS -- but both are checking the
    # same underlying reality (NEMWeb only publishes each AEST calendar
    # day's dispatch file ~4am the *following* day, see
    # AEMONEMFetcher.fetch_for_date's docstring), so this needs the same
    # 30h threshold quality.py already uses: a tighter value here proved
    # live (see TODO.md) to abort the *entire* incremental run at Stage 1
    # on every event-triggered tick where aemo_nem/aemo_wem simply hadn't
    # had a new day published yet, even though bom/openelectricity/
    # holidays had perfectly good new data dbt could have processed.
    freshness_threshold_aemo: timedelta = timedelta(hours=30)
    freshness_threshold_bom: timedelta = timedelta(hours=2)
    freshness_threshold_holidays: timedelta = timedelta(days=7)

    # ── Quality thresholds ────────────────────────────────────────────────
    max_null_pct: float = Field(default=0.10, ge=0.0, le=1.0)
    max_consecutive_gap_minutes: int = 90  # 1.5h gap in 30-min series = error

    # ── Retention ─────────────────────────────────────────────────────────
    vacuum_after_hours: int = Field(default=24, ge=1)
    raw_retention_days: int = Field(
        default=30,
        ge=1,
        description=(
            "How much history the archive stage keeps in Postgres raw.* "
            "before trimming (DuckDB is unaffected -- it's the permanent "
            "raw store and always retains everything; raw.* is just a "
            "synced working copy for dbt, safely rebuildable from DuckDB "
            "via --full). Left untrimmed, raw.* regrows toward NeonDB's "
            "512MB free-tier project cap within months."
        ),
    )

    # ── Raw sync (DuckDB -> PostgreSQL raw.*, ecolens.ingestion.repository.raw_sync) ──
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
