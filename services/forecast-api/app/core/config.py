"""forecast-api runtime configuration.

Mirrors `data-pipeline`'s `app.core.config.Settings` in shape (same env
var names/defaults where both services need the same infra —
`DATABASE_URL`, `REDIS_URL`, `MLFLOW_TRACKING_URI` — so one `.env` file
configures both), but is its own independent `Settings` class: the two
services are separate Python packages, each installed into their own
venv (see this package's `__init__.py`), and don't share code beyond
what's deliberately duplicated (`models/ml.py`, `service/ml/features.py`
— see their own docstrings).
"""

from __future__ import annotations

import socket
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    api_port: int = 8000
    api_cors_origins: list[str] = ["*"]

    database_url_env: str | None = Field(default=None, validation_alias="DATABASE_URL")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ecolens"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

    redis_url_env: str | None = Field(default=None, validation_alias="REDIS_URL")
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_registry_model_name: str = "lstm_demand"
    # `train-energy-forecast`'s registered model name (`data-pipeline`'s
    # `ml/train_energy_forecast.py`'s `DEFAULT_MODEL_NAME`) -- served by
    # its own `EnergyModelRegistry`, alongside (not instead of) the
    # single-task model above.
    energy_forecast_model_name: str = "energy_forecast_multi_task"
    # How often the background task checks MLflow for a newer Production
    # version (`README.md`: "forecast-api hot-reloads it on the next
    # request... just a watch on the MLflow registry").
    model_reload_interval_seconds: float = 60.0

    forecast_cache_ttl_seconds: int = 60

    # `TODO.md` Forecasting Phase 4's "Self-Correction & Fallback
    # Mechanism" -- `service/ml/forecast_reconciliation.py`'s background
    # sweep, comparing what was served against real demand once it
    # lands, driving `service/ml/forecast_breaker.py`'s circuit breaker.
    # 30 minutes -- frequent enough that a real model regression trips
    # the breaker (and starts serving the baseline fallback) well within
    # an hour of the first bad prediction reconciling, without hammering
    # `raw_marts.fct_energy_demand` on every single request the way a
    # per-request check would.
    forecast_reconciliation_interval_seconds: float = 1800.0
    forecast_error_threshold_pct: float = 15.0

    # `TODO.md` Forecasting Phase 7's "OpenTelemetry Instrumentation" --
    # same real-no-op-when-disabled pattern `services/waerehouse`'s
    # identical settings use; exports to `services/observility`'s
    # already-configured Collector when enabled, never straight to
    # Tempo.
    otel_traces_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    # Bound as a static field on every log line (`core/logging.py`) --
    # matches `services/observility/prometheus/prometheus.yml.template`'s
    # own hardcoded `external_labels.environment: development` default.
    environment: str = "development"

    emissions_cache_ttl_seconds: int = 60
    emissions_ytd_cache_ttl_seconds: int = 300
    footprint_cache_ttl_seconds: int = 300
    # `WS /v1/stream/emissions` (`README.md`'s API table: "Server-sent
    # stream, 5-min updates").
    stream_interval_seconds: float = 300.0

    # `todo-model-training.md` Phase 7: how stale
    # `fct_carbon_intensity.live_provider_intensity_kgco2e_per_mwh` (an
    # hourly rollup) can be before `service/ml/data.py`'s fallback logic
    # stops trusting it and falls back to the derived
    # `live_mix_weighted` figure instead. 90 minutes -- one full hourly
    # bucket plus real ingestion/dbt-build lag, not just "the current
    # hour" (which would spuriously call last hour's genuinely-current
    # data "stale" for the first few minutes of every new hour).
    emissions_provider_freshness_minutes: float = 90.0

    # ML training tunables -- ported from data-pipeline's identical
    # fields as part of the training-code migration (this service trains
    # now, not just serves). Same defaults, same reasoning (see that
    # service's own `core/config.py` comments for the full rationale
    # behind each number).
    model_train_epochs: int = 50
    model_train_lr: float = 1e-3
    model_hidden_size: int = 128
    model_dropout: float = 0.5
    model_num_layers: int = 2
    model_lookback: int = 48
    model_horizon: int = 48
    model_batch_size: int = 64
    model_quantile_weight: float = 1.0
    model_early_stopping_patience: int = 5
    # `ml/conformal.py`'s target miscoverage -- 0.2 -> an 80% (P10-P90)
    # interval.
    conformal_alpha: float = 0.2
    # Fraction of the (already time-split) validation set reserved for
    # conformal calibration rather than early-stopping -- see
    # `ml/train.py`'s docstring for why these must be disjoint.
    model_cal_frac: float = 0.5
    # Regions `train`/`train-tft` trains across when no `--region` is
    # passed.
    model_default_regions: list[str] = ["NSW1"]

    # Incremental (warm-started) training tunables -- `ml/incremental.py`.
    # Deliberately much lighter than `model_train_epochs`/`model_train_lr`'s
    # from-scratch defaults: a fine-tune that starts from an existing
    # Production/Staging version's weights needs far fewer steps and a
    # smaller learning rate to adapt to a small recent data window
    # without overwriting what the full retrain already learned.
    incremental_train_epochs: int = 3
    incremental_train_lr: float = 1e-4
    incremental_train_window_hours: int = 24

    # RabbitMQ training-trigger topology (consume + publish) -- this
    # service now owns `app.service.training_worker` (the `train-worker`
    # docker-compose service / `ecolens-forecast train-worker` CLI
    # command, ported from data-pipeline's identical consumer) plus the
    # manual `POST /v1/model/train` publish path. Same names/topology
    # `services/waerehouse`'s publish-only copy uses (`app/db/rabbitmq.py`
    # there) -- the queue/exchange names are the one real coupling point
    # between the two services.
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_training_exchange: str = "forecasting.training"
    rabbitmq_training_routing_key: str = "training.trigger"
    rabbitmq_training_trigger_queue: str = "forecasting.training.trigger"
    rabbitmq_training_dlx: str = "forecasting.training.dlx"
    rabbitmq_training_trigger_dlq: str = "forecasting.training.trigger.dlq"

    # Recorded in `meta._training_log` -- lets an operator tell which
    # process/host ran a given training run, same role data-pipeline's
    # identical `hostname` field played before this migration.
    hostname: str = Field(default_factory=socket.gethostname)

    @property
    def database_url(self) -> str:
        if self.database_url_env:
            url = self.database_url_env
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            url = url.replace("sslmode=", "ssl=")
            return url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_url_env:
            return self.redis_url_env
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
