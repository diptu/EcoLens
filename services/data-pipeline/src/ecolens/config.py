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

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_dsn: RedisDsn = Field(  # type: ignore[assignment]
        default="redis://redis:6379/0",
        description="Async Redis URL.",
    )

    # ── RabbitMQ ──────────────────────────────────────────────────────────
    # Ingestion's sole write path (duckdb_store.write_historical) publishes
    # a "data written" event here as soon as new/updated rows land in
    # DuckDB; ecolens.warehouse.service.event_consumer consumes it and
    # triggers an incremental WarehouseRunner run -- an event-driven
    # replacement for the old every-30-min warehouse cron. Defaults assume
    # a locally-running broker reachable from the host (this repo's
    # processes all run directly on the host, not inside docker-compose's
    # network -- same assumption NEON_DSN/MONGO_URI already make), not the
    # in-container "rabbitmq" hostname docker-compose's other services use.
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_queue: str = "ecolens.warehouse.trigger"

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
        },
        description=(
            "Region -> canonical BoM station ID. Feeds the historical "
            "(Open-Meteo/ERA5) fetcher's output rows and the synthetic-stub "
            "tier -- NOT the live v1 API's request URL, see bom_geohashes."
        ),
    )
    bom_geohashes: dict[str, str] = Field(
        default_factory=lambda: {
            "NSW1": "r3gx2s",  # Sydney - Observatory Hill
            "QLD1": "r7huht",  # Brisbane
            "VIC1": "r1qcxv",  # Melbourne
            "SA1": "r1f90q",  # Adelaide
            "TAS1": "r22u08",  # Hobart
            "WEM": "qd66qd",  # Perth Airport
        },
        description=(
            "Region -> 6-char BoM geohash for the live v1 observations API "
            "(api.weather.bom.gov.au/v1/locations/{geohash}/observations). "
            "Look up new ones via /v1/locations?search=<city>."
        ),
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
            "Local DuckDB file the ingestion layer writes into -- the sole "
            "raw-data store for the pipeline (see "
            "ingestion/storage/duckdb_store.py). Relative to CWD by "
            "default, like bom_cache_dir/training_snapshot_dir above."
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

    # ── TFT tunables (forecasting/model/tft.py) ─────────────────────────────
    # Registered/scoped separately from the LSTM above (own MLflow
    # experiment + registered-model name) rather than sharing
    # mlflow_experiment_name/mlflow_registered_model_name -- lets both
    # architectures hold their own "production" alias without competing for
    # the same registry entry. model_lookback/model_horizon/
    # model_early_stop_patience/conformal_alpha/model_registry_alias above
    # are architecture-agnostic and reused as-is.
    model_tft_d_model: int = 64
    model_tft_num_heads: int = 4
    model_tft_num_lstm_layers: int = 1
    model_tft_static_dim: int = 16
    model_tft_dropout: float = 0.1
    model_tft_train_lr: float = 1e-3
    model_tft_train_epochs: int = 50
    model_tft_batch_size: int = 64
    mlflow_experiment_name_tft: str = "ecolens-demand-tft"
    mlflow_registered_model_name_tft: str = "ecolens_demand_tft"

    # ── TimesFM tunables (forecasting/service/serving/timesfm_backbone.py,
    # forecasting/model/timesfm_head.py) ────────────────────────────────────
    # TimesFM itself is a frozen pretrained foundation model (Google,
    # via Hugging Face Hub) -- nothing here trains it. `timesfm_*` config
    # is for loading/running the frozen backbone; `model_timesfm_*` is for
    # the small calibration head trained on top of its output. Registered
    # separately, same reasoning as the TFT fields above.
    timesfm_repo_id: str = "google/timesfm-2.5-200m-pytorch"
    timesfm_per_core_batch_size: int = 32
    model_timesfm_hidden_dim: int = 32
    model_timesfm_static_dim: int = 16
    model_timesfm_dropout: float = 0.1
    model_timesfm_train_lr: float = 1e-3
    model_timesfm_train_epochs: int = 50
    model_timesfm_batch_size: int = 64
    mlflow_experiment_name_timesfm: str = "ecolens-demand-timesfm"
    mlflow_registered_model_name_timesfm: str = "ecolens_demand_timesfm"
    # ── Per-fuel LightGBM ensemble (forecasting/model/fuel_ensemble.py) ─────
    # Root TODO.md "Normalization Constraint Layer": 16 independent
    # per-fuel regressors, one LGBMRegressor each -- not a torch model,
    # same LightGBM precedent feature_selection.py's Step 4 already sets
    # in this codebase (including that module's n_jobs=1 SIGSEGV landmine
    # from importing torch and LightGBM's multi-threaded OpenMP pool in
    # the same process -- training/train_fuel_ensemble.py inherits the
    # same fix). Registered under its own MLflow experiment/registered-
    # model name, same reasoning as the TFT/TimesFM fields above -- no
    # "production" alias contention with the demand-forecasting models.
    model_fuel_num_leaves: int = 31
    model_fuel_n_estimators: int = 200
    model_fuel_learning_rate: float = 0.05
    model_fuel_max_depth: int = -1
    mlflow_experiment_name_fuel_ensemble: str = "ecolens-fuel-ensemble"
    mlflow_registered_model_name_fuel_ensemble: str = "ecolens_fuel_ensemble"
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
        # :3000 is `pnpm dev`; :8000 is `pnpm serve`'s static-export
        # preview, which is what services/dashboard's own e2e suite
        # (playwright.config.ts's default baseURL) actually targets.
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8000"]
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
