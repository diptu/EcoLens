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
    cache_ttl_seconds: int = 300

    # ── API ───────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"  # nosec B104 - must bind all interfaces inside the container
    api_port: int = 8003
    api_key: str | None = Field(
        default=None,
        description="If set, require a matching X-API-Key/api_key on every request.",
    )
    # Gunicorn worker count for production (see gunicorn_conf.py, ECO-F01).
    # None -> gunicorn_conf.py derives it from CPU count ((2 * cores) + 1,
    # capped) instead of a fixed number, since that scales sanely across
    # different container sizes without a per-environment override.
    web_concurrency: int | None = Field(
        default=None,
        ge=1,
        description="Gunicorn worker process count. Unset = auto (CPU-based).",
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
    # Must match data-pipeline Settings.model_lookback -- the real LSTM's
    # input window length (ECO-F05/F06). Irrelevant to the baseline
    # forecaster, which reads the mart's precomputed lag columns instead.
    model_lookback: int = 48
    # 80% interval (conformal_alpha=0.1 in data-pipeline's Settings), applied
    # naively via the mart's rolling stddev -- see baseline.py's docstring for
    # why this is not true conformal calibration.
    interval_z_score: float = 1.2816

    # ── Model loading (ECO-F02..F09) ────────────────────────────────────────
    # Points at the same MLflow tracking server data-pipeline trains
    # against and registers models to -- this service only ever reads
    # from it (strategy.md §2: forecast-api never trains).
    mlflow_tracking_uri: str = "http://mlflow:5000"
    # Must match data-pipeline Settings.mlflow_registered_model_name.
    mlflow_registered_model_name: str = "ecolens_demand_lstm"
    # Must match data-pipeline Settings.model_registry_alias. Reassigning
    # this alias to a new version in the registry is the hot-swap signal
    # this service's reload loop (ECO-F04) polls for.
    model_alias: str = "production"
    model_reload_interval_seconds: int = Field(
        default=60,
        ge=5,
        description=(
            "How often to poll the registry for a new model_alias version. "
            "strategy.md §7: polling, not a push signal from data-pipeline "
            "on promotion -- revisit if reload latency (time-to-serve after "
            "promotion) turns out to matter more than this simplicity."
        ),
    )
    # MLflow's own defaults here are 120s timeout x 7 retries -- fine for a
    # long-running training job, disastrous for a poll that runs every
    # `model_reload_interval_seconds` and (on the first one) blocks app
    # startup: a briefly-unreachable MLflow server could otherwise stall
    # this service from ever becoming ready for 10+ minutes. Fail fast
    # instead -- a skipped reload attempt costs nothing, since the
    # baseline forecaster keeps `/v1/forecast` working the whole time
    # (ECO-F06) and the next poll tries again in
    # model_reload_interval_seconds.
    mlflow_http_timeout_seconds: int = Field(default=5, ge=1)
    mlflow_http_max_retries: int = Field(default=1, ge=0)
    inference_device: str = "cpu"
    # ECO-F07: which CPU inference optimization (if any) to apply to a
    # freshly loaded model. "none" is the safe default; quantized models
    # trade a small accuracy hit for lower latency/memory (strategy.md §5),
    # and should only be turned on after the ECO-P03 benchmark says it's
    # worth it for this specific model size.
    inference_optimization: str = Field(
        default="none",
        pattern="^(none|dynamic_quantization)$",
        description="'none' or 'dynamic_quantization' (torch.quantization.quantize_dynamic).",
    )


@lru_cache(maxsize=1)
def get_forecast_api_settings() -> ForecastApiSettings:
    """Cached settings singleton. Same pattern as `ecolens.config.get_settings()`."""
    return ForecastApiSettings()


__all__ = ["ForecastApiSettings", "get_forecast_api_settings"]
