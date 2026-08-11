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
    # `GET /v1/model/drift` -- `compute_drift` re-scans two chronological
    # slices of real training data per call (confirmed live: 7-8s,
    # uncached, before 2026-08-11). Real feature distributions don't
    # meaningfully shift on a sub-minute cadence, so 5 minutes is honest,
    # not stale in any way the dashboard's own drift alert cares about.
    model_drift_cache_ttl_seconds: int = 300
    # `GET /v1/forecast/recent-actual-vs-predicted` -- a real walk-forward
    # re-forecast, previously entirely uncached (`region=NEM` alone sums
    # 5 independent per-region re-forecasts server-side, confirmed slow
    # enough that `lib/emissions.ts`'s `fetchRecentBacktest` uses a 45s
    # timeout instead of every other call's 15s default). The real origin
    # this anchors to only advances as new actual demand lands (hourly at
    # best), so 5 minutes is honest, not stale in any way the Forecast
    # Explorer's "Actual vs Predicted" chart cares about -- same
    # reasoning as `model_drift_cache_ttl_seconds` above.
    recent_backtest_cache_ttl_seconds: int = 300

    # `app.service.cache_warmer` -- all comfortably shorter than the
    # respective TTL above, so a background refresh always lands before
    # a real request could ever hit an expired (cold) entry.
    emissions_forecast_warmer_interval_seconds: float = 45.0
    model_drift_warmer_interval_seconds: float = 240.0
    # `run_dashboard_essentials_warmer` -- covers `GET /v1/forecast`
    # (region=NEM) among several other cheaper endpoints, all on
    # `forecast_cache_ttl_seconds`/`emissions_cache_ttl_seconds` (60s) or
    # longer TTLs -- 40s stays under the tightest of those with a real
    # margin, same reasoning as the other two warmers above.
    dashboard_essentials_warmer_interval_seconds: float = 40.0

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
    # Was 0.5 -- real, measured overfitting symptom (large train-vs-val
    # gap) on a 2-layer LSTM; 0.5 between only 2 stacked layers is
    # aggressive enough to hurt sequential learning on top of whatever
    # regularization benefit it adds. Lowered to the middle of a more
    # standard 0.2-0.3 range for time-series LSTMs, not the extreme end.
    model_dropout: float = 0.25
    # L2 regularization on Adam -- previously absent entirely (confirmed:
    # `torch.optim.Adam(model.parameters(), lr=config.lr)` had no
    # `weight_decay` kwarg anywhere in train.py/train_energy_forecast.py/
    # train_tft.py). Real gap, not a hypothetical one -- same train-vs-val
    # overfitting symptom above. 1e-5, the conservative end of a
    # 1e-4-1e-5 range: a real optimizer/regularization change to a
    # production-serving model warrants starting light and letting
    # `tune.py`'s Optuna search (which now covers this dimension too)
    # find a stronger value if the data actually calls for one, rather
    # than guessing a large penalty upfront.
    model_weight_decay: float = 1e-5
    model_num_layers: int = 2
    # Row-offset lookback/horizon at each region's own native ingestion
    # grain (5-min for NEM, 30-min for WEM) -- shared, as-is, by
    # `EnergyTrainConfig` (`train_energy_forecast.py`, the separate
    # `energy_forecast_multi_task` model) and `TFTTrainConfig`
    # (`train_tft.py`, inherits `TrainConfig.from_settings()` directly).
    # Deliberately NOT changed for the demand-model's 7-day/hourly-grain
    # retrain below -- `EnergyTrainConfig`'s own module comment already
    # documents its row-offset scheme as an accepted, separate trade-off
    # for that model; repurposing this shared field would have silently
    # changed its training window too, never reviewed for that model.
    model_lookback: int = 48
    model_horizon: int = 48
    # Dedicated to the demand model (`TrainConfig`, `lstm_demand` +
    # `lstm_demand_tft` via `TFTTrainConfig` inheriting `TrainConfig.
    # from_settings()`) specifically -- at *hourly* grain, not row-offset
    # like `model_lookback`/`model_horizon` above. Hourly is what lets WEM
    # join the same shared-weight model as the 5 NEM regions for the
    # first time -- its native 30-min rows and NEM's native 5-min rows
    # only mean the same real wall-clock span per step once both are
    # resampled to a common grain. `ml/data.py`'s hourly aggregation is
    # what actually produces that grain; these two numbers are moot
    # without it.
    #
    # 24/48 (1-day lookback, 2-day horizon) -- NOT the originally-planned
    # 7-day (168h) horizon. Real, measured, code-verified constraint, not
    # a design preference: `fct_energy_demand`'s real live history is far
    # shorter than earlier assumed (~60 days) -- NEM regions only have
    # ~14 days (~300 real hourly rows after gaps), WEM ~44 days. At
    # horizon=168h, even a SINGLE training window for a NEM region alone
    # needs 64%+ of its total 300 rows, leaving no room for genuinely
    # separate (non-leaky) held-out val/cal windows under any split-
    # fraction arrangement -- confirmed by directly running the real
    # windowing code across a horizon sweep (168h down to 48h), not by
    # formula alone. 48h is the largest horizon that gives every one of
    # the 6 regions multiple real, non-empty train/val/cal windows today
    # (measured: ~64 train/~26 val/~27 cal per NEM region, ~416/~202/~203
    # for WEM) -- see `TrainConfig.train_frac`/`val_frac`'s own comment
    # (`ml/train.py`) for the matching split-fraction change this
    # required. Revisit the full 7-day ask once NEM's real ingestion
    # (~21 rows/day since 2026-07-24) reaches enough history for a
    # non-thin evaluation -- estimated ~2026-08-18/19, not the originally
    # estimated 5-6 weeks (that estimate used too coarse a formula).
    model_demand_lookback: int = 24
    model_demand_horizon: int = 48
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
    # passed. Was `["NSW1"]` -- now all 6 real regions (5 NEM + WEM),
    # since the hourly-grain retrain (see `model_lookback`/`model_horizon`
    # above) is specifically what makes training WEM alongside the NEM
    # regions temporally coherent for the first time.
    model_default_regions: list[str] = ["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"]

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
