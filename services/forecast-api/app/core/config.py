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

    # Separate Postgres instance (2026-08-12) for the real "logger"
    # tables this service writes/reads (`meta._training_log`,
    # `meta.anomalies` reads, `meta._dbt_build_log` reads) -- same split
    # `services/ingestion`/`services/waerehouse` use, for the same
    # reason. Falls back to `database_url` when unset. **Must be the
    # identical value those two services use** -- `meta.anomalies.
    # run_id` has a real foreign key into `meta._ingest_log(id)`, so
    # those tables can never live in different databases from each other.
    log_db_url_env: str | None = Field(default=None, validation_alias="LOG_DB_URL")

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
    # best). Bumped 300 -> 1800 (2026-08-11): `region=NEM, days=30` (the
    # dashboard's "Emission History" 30-day forecast band) is now
    # confirmed live at ~158s to compute (grew from ~50s as real history
    # has accumulated) -- kept warm by `run_recent_backtest_warmer`
    # well under this TTL, so 30 minutes is just a safety margin against
    # a missed/delayed warm pass, not the real staleness tolerance
    # (which, per the note above, is honestly ~1h either way).
    recent_backtest_cache_ttl_seconds: int = 1800

    # `app.service.cache_warmer` -- all comfortably shorter than the
    # respective TTL above, so a background refresh always lands before
    # a real request could ever hit an expired (cold) entry.
    emissions_forecast_warmer_interval_seconds: float = 45.0
    model_drift_warmer_interval_seconds: float = 240.0
    # `region=NEM, days=30` -- confirmed live at ~158s to compute
    # (`recent_backtest_cache_ttl_seconds`'s own comment), so this needs
    # its own dedicated loop (same reasoning as the two intervals above,
    # not folded into `dashboard_essentials_warmer_interval_seconds`
    # which is for endpoints an order of magnitude cheaper). 20 minutes
    # keeps a wide margin under the 30-minute TTL (~2 warm-cycle buffer
    # if one pass is delayed) while keeping this warmer's own duty cycle
    # reasonable (~158s of real compute every 1200s, not a tight loop).
    recent_backtest_warmer_interval_seconds: float = 1200.0
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
    # Real bug, confirmed live 2026-08-11: `training_worker._run_live_
    # evaluation_gate` calls `evaluate.run_live_evaluation_gate` without
    # ever passing `max_acceptable_mape`, so that function's own
    # `passed = bool(scored)` was the *entire* real check in production
    # -- a version tags `eval_gate_passed="True"` as long as evaluation
    # ran against *any* real data, regardless of how bad its real
    # out-of-sample MAPE is. `promote_version`'s "never force-skippable"
    # live-eval gate -- specifically built to catch "a version that
    # overfit... can still show a fine training-time test_mape" -- was a
    # paper tiger for exactly that scenario. Confirmed live: the current
    # Production LSTM (v7)'s real walk-forward MAPE is *worse* than the
    # trivial seasonal-naive baseline in 5 of 6 regions (WEM: 18.85% vs
    # naive's 8.38%) yet still carries `eval_gate_passed="True"`.
    #
    # `training_worker._resolve_max_acceptable_mape` now computes a real
    # ceiling from the current Production version's own real
    # `eval_gate_mape` times `1 + this/100` -- relative to a real
    # current baseline, same "relative regression, not an arbitrary
    # absolute number" shape `prune.py`'s `max_relative_mape_regression_
    # pct` already established for the (much smaller) prune-recovery
    # case. 20%, not `prune`'s tight 1%: a full/incremental retrain is a
    # materially bigger real change (fresh random init or a real new
    # data window, not the same weights minus some units) with real
    # measured run-to-run noise on this little data (single-split
    # val_mape swung 8.02%-14.26% across ~10 nominally-identical
    # historical runs) -- 1% here would reject good real retrains on
    # noise alone. `None` (no baseline yet -- the very first version
    # ever registered for a `model_name`, or a Production version that
    # predates the live-eval-gate tagging and so has no real
    # `eval_gate_mape` of its own) leaves the gate ungated, same "absent
    # signal doesn't block" convention `promote_version`'s own two gates
    # already follow. Deliberately does NOT fall back to Production's
    # `test_mape` when `eval_gate_mape` is missing (real bug, confirmed
    # live 2026-08-12: that compared a candidate's real walk-forward
    # MAPE against an easier single-split metric with only this 20%
    # tolerance, rejecting v16 -- 11.01 real walk-forward, roughly a
    # wash against v7's *own* ~11.24 computed the same way -- against
    # v7's `test_mape` of 8.19, an apples-to-oranges threshold).
    # `_resolve_max_acceptable_mape`'s own docstring has the full story.
    live_eval_gate_max_regression_pct: float = 20.0
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
    # `ml/prune.py`'s `prune_and_recover` -- real bug, confirmed live
    # 2026-08-11: this used to fall back to `incremental_train_epochs`
    # (3) when no explicit `recovery_epochs` was given, which is right
    # for incremental's own "small nudge to an unchanged architecture"
    # use case but nowhere near enough to recover from an actual
    # structural cut (default `--keep-fraction 0.5` removes *half* the
    # LSTM's hidden units). Measured live at `keep_fraction=0.5` against
    # a real registered version: 3 epochs left `train_model`'s own loss
    # curve still steeply descending (val_mape 85%->61%->37%, nowhere
    # near converged) and produced a +131.2% relative walk-forward MAPE
    # regression -- past the pipeline's own accuracy-tolerance gate
    # (`max_relative_mape_regression_pct`, tightened 2%->1% 2026-08-11)
    # by ~131x, i.e. every default prune was guaranteed to fail it. 15
    # epochs already recovered past *better* than the unpruned version
    # (-21.1% relative, comfortably inside even the tightened 1% bar);
    # 20 keeps a real margin above that without meaningfully more
    # compute (~0.6s/epoch on this dataset). Still overridable per-call
    # (`--recovery-epochs`, `ecolens-forecast prune`) for a more
    # aggressive `keep_fraction` that might genuinely need more.
    prune_recovery_epochs: int = 20
    # Real bug, confirmed live 2026-08-11: 24h guaranteed `train_model`'s
    # own "not enough history" `ValueError` (`ml/train.py`) for every
    # single incremental trigger, automatic (`services/waerehouse`'s
    # post-dbt-build publish, which uses this exact same default) or
    # manual (the dashboard Fine-tune form, whose own default window
    # mirrored this value) alike -- not an edge case, the *only* case,
    # every time. The real math: at `model_demand_lookback`/
    # `model_demand_horizon` (24/48 above), `train_model`'s per-region
    # window count needs roughly `train_frac * W > lookback + horizon`
    # for a train window and `(1 - train_frac) * cal_frac * W > horizon`
    # for a calibration window (val/cal windows borrow lookback context
    # backward across the split boundary into train, so only train's
    # own slice needs the full lookback+horizon span) -- with this
    # service's real `train_frac=0.49`/`cal_frac=0.5`, that's `W > ~196`
    # real hourly rows, and 24h of *calendar* time, even at perfect
    # density, is only 24 rows. 336h (14 days) matches the "~14 days"
    # this file's own `model_demand_lookback`/`model_demand_horizon`
    # comment already measured as enough real history for NEM (the
    # thinnest of the 6 regions) to produce multiple non-thin windows,
    # not just clear the bare minimum.
    incremental_train_window_hours: int = 336

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
    def log_db_url(self) -> str:
        """`postgresql+asyncpg://` DSN for the separate logging database
        (`db.session.get_log_engine`) -- uses `LOG_DB_URL` verbatim (same
        normalization as `database_url`) if set, else falls back to
        `database_url` itself."""
        if self.log_db_url_env:
            url = self.log_db_url_env
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            url = url.replace("sslmode=", "ssl=")
            return url
        return self.database_url

    @property
    def redis_url(self) -> str:
        if self.redis_url_env:
            return self.redis_url_env
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
