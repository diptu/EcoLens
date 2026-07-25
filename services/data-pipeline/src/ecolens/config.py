"""ecoLens data-pipeline configuration.

Single source of truth for runtime settings. Reads from environment
variables and a `.env` file. Validated at import time so a misconfigured
deployment fails fast on container start.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Data-pipeline runtime settings.

    All fields are loaded from environment variables. The service
    container supplies them via docker-compose's `env_file: .env`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Identity ──────────────────────────────────────────────────────────
    service_name: str = "ecolens-data-pipeline"
    env: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── Postgres (TimescaleDB) ────────────────────────────────────────────
    postgres_dsn: PostgresDsn = Field(  # type: ignore[assignment]
        default="postgresql+asyncpg://ecolens:ecolens@postgres:5432/ecolens",
        description="Async SQLAlchemy DSN. Use postgresql+asyncpg://.",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_echo: bool = False

    # ── MongoDB ─────────────────────────────────────────────────────────
    mongo_uri: str = Field(
        default="mongodb://mongo:27017",
        description="MongoDB connection string.",
    )
    mongo_db_name: str = Field(
        default="ecolens",
        description="Default database name for the ecoLens collections.",
    )
    mongo_max_pool_size: int = 20
    mongo_min_pool_size: int = 5
    mongo_server_selection_timeout_ms: int = 5000
    mongo_connect_timeout_ms: int = 10_000
    mongo_socket_timeout_ms: int = 30_000
    mongo_retry_reads: bool = True
    mongo_retry_writes: bool = True

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_dsn: RedisDsn = Field(  # type: ignore[assignment]
        default="redis://redis:6379/0",
        description="Async Redis URL.",
    )

    # ── S3 / MinIO ────────────────────────────────────────────────────────
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_raw: str = "ecolens"
    s3_bucket_models: str = "ecolens"
    s3_region: str = "us-east-1"

    # ── MLflow ────────────────────────────────────────────────────────────
    mlflow_tracking_uri: str = "http://mlflow:5000"
    mlflow_s3_endpoint_url: str = "http://minio:9000"
    mlflow_artifact_root: str = "s3://ecolens/mlflow"

    # ── Upstream APIs ─────────────────────────────────────────────────────
    bom_stations: dict[str, str] = Field(
        default_factory=lambda: {
            "NSW1": "066037",  # Sydney
            "QLD1": "040913",  # Brisbane
            "VIC1": "086282",  # Melbourne
            "SA1": "023034",  # Adelaide
            "TAS1": "094029",  # Hobart
            "WEM": "009225",  # Perth
        }
    )

    # ── Ingest tunables ───────────────────────────────────────────────────
    default_lookback_minutes: int = 30
    oe_api_key: str | None = Field(
        default=None,
        description="OpenElectricity (OpenNEM) API bearer token.",
    )
    oe_request_timeout_seconds: int = 30
    aemo_request_timeout_seconds: int = 60
    bom_request_timeout_seconds: int = 30
    bom_cache_dir: Path = Field(
        default=Path("data/raw/bom"),
        description=(
            "Local CSV cache dir for BomFetcher's tier-2 fallback. Relative to "
            "the CWD by default (no /data volume is mounted anywhere in this "
            "repo's docker-compose yet) — override via BOM_CACHE_DIR for a "
            "deployment that does mount one."
        ),
    )
    holidays_cache_dir: Path = Field(
        default=Path("data/raw/holidays"),
        description=(
            "Local CSV cache dir for HolidayFetcher's tier-2 fallback. Relative "
            "to the CWD by default — override via HOLIDAYS_CACHE_DIR."
        ),
    )
    historical_duckdb_path: Path = Field(
        default=Path("data/historical/ecolens_historical.duckdb"),
        description=(
            "Local DuckDB file the ingestion layer's historical backfills "
            "(e.g. HistoricalFetcher's ERA5 backfill, see "
            "ingestion/storage/duckdb_store.py) write into, in addition to "
            "MongoDB -- a durable, queryable record that survives "
            "warehouse/runner/archive.py's age-based Mongo deletion. Relative "
            "to CWD by default, like bom_cache_dir/training_snapshot_dir above."
        ),
    )

    # ── ML tunables ───────────────────────────────────────────────────────
    model_lookback: int = 48  # input window in 30-min intervals
    model_horizon: int = 48  # forecast horizon
    model_train_epochs: int = 50
    model_train_lr: float = 1e-3
    model_early_stop_patience: int = 10
    model_hidden_size: int = 128
    model_num_layers: int = 2
    model_dropout: float = 0.2
    model_batch_size: int = 64
    optuna_n_trials: int = 50
    hyperparameter_search_config_path: Path = Field(
        default=Path("hyperparameter_search.yml"),
        description=(
            "ECO-113: YAML file defining the Optuna search space "
            "training/tune.py searches over (which hyperparameters, their "
            "type/range/choices). Relative to CWD by default, matching this "
            "repo's local-disk convention -- see "
            "forecasting/training/search_space.py. Missing file falls back "
            "to a hardcoded default search space, not an error, so existing "
            "callers/tests that don't ship this file keep working."
        ),
    )
    conformal_alpha: float = 0.1  # → 80% prediction interval
    mlflow_experiment_name: str = "ecolens-demand-lstm"
    mlflow_registered_model_name: str = "ecolens_demand_lstm"
    model_registry_alias: str = "production"
    training_snapshot_dir: Path = Field(
        default=Path("data/training_snapshots"),
        description=(
            "Where ECO-109's TrainingSetLoader writes versioned Parquet "
            "snapshots of ml_features_demand_v1 (see forecasting/data.py) -- "
            "local disk by default like bom_cache_dir/holidays_cache_dir "
            "above; point at a mounted volume for a deployment that has one."
        ),
    )

    # ── Drift detection ───────────────────────────────────────────────────
    drift_psi_threshold: float = 0.2
    drift_residual_ks_alpha: float = 0.01
    drift_lookback_days: int = 7

    # ── FastAPI server ────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"  # nosec B104 - must bind all interfaces inside the container
    api_port: int = 8001
    api_cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    api_workers: int = 1

    # ── Operational ───────────────────────────────────────────────────────
    hostname: str = "unknown"
    ingest_default_triggered_by: str = "manual"
    backfill_batch_days: int = 7

    # ── Derived paths ─────────────────────────────────────────────────────
    @property
    def dbt_project_dir(self) -> Path:
        """Resolved path to the dbt project (mounted at /app/dbt in container)."""
        return Path("/app/dbt/ecolens")

    @property
    def migrations_dir(self) -> Path:
        return Path(__file__).parent.parent.parent / "migrations"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton.

    First call instantiates and validates the Settings object. Subsequent
    calls return the cached instance, so reading `get_settings()` is cheap.
    """
    return Settings()  # type: ignore[call-arg]
