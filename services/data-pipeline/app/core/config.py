"""ecoLens data-pipeline configuration.

Single source of truth for runtime settings. Reads from environment
variables and a `.env` file. Validated at import time so a misconfigured
deployment fails fast on container start.

Field groups mirror README.md's stack: PostgreSQL 16 (+ TimescaleDB),
Redis 7, MinIO/S3 (MLflow artifact store), MLflow tracking, BoM weather
stations, and the LSTM training tunables described in README § ML pipeline
("2-layer nn.LSTM (hidden=128, dropout=0.2)").
"""

from __future__ import annotations

import socket
from functools import lru_cache
from typing import Literal

from pydantic import Field
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

    # API — this service's own FastAPI control plane (README's original
    # design had data-pipeline as headless; the port below matches the
    # data-pipeline.Dockerfile CMD planned in TODO.md's ECO-D49).
    api_port: int = 8001
    api_cors_origins: list[str] = ["*"]

    # Postgres 16 + TimescaleDB (README § Tech stack -> Warehouse).
    # `database_url_env` (env var `DATABASE_URL`) takes priority over the
    # decomposed fields below when set — this repo's own `.env` (and most
    # managed Postgres providers, e.g. Neon) hands you a single DSN, not
    # separate host/port/user/password/db values.
    database_url_env: str | None = Field(default=None, validation_alias="DATABASE_URL")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ecolens"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

    # Redis 7 (README § Tech stack -> Cache). Same override pattern as
    # `database_url_env` above — a hosted Redis (e.g. Upstash) hands you
    # one `redis://`/`rediss://` URL, not decomposed fields.
    redis_url_env: str | None = Field(default=None, validation_alias="REDIS_URL")
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # MinIO / S3 — MLflow artifact store (README § ML pipeline -> MLflow:
    # `--default-artifact-root s3://ecolens/mlflow`).
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "ecolens"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"

    # MongoDB. LEGACY — superseded by the DuckDB+RabbitMQ raw-landing
    # design below (`overview.md`/`README.md`); no longer required or used
    # by the hot ingest path. Kept only because `pipeline.landing`'s old
    # `land_to_mongodb_blob`/`land()`/`landing_backend` dispatch (below)
    # still exists as an unused-but-tested utility, not wired into
    # `pipeline.tasks._common.standard_run` anymore. Safe to delete once
    # that legacy code is removed — see `TODO.md`'s Ingestion section.
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db: str = "ecolens"

    # LEGACY — `pipeline.landing.land()`'s audit-trail blob backend
    # (`s3`/`postgres`/`mongodb`). Superseded by DuckDB-staged files
    # (`duckdb_staging_dir` below) being the audit/replay artifact now;
    # `land()`/`land_and_load()` still exist and still work, they're just
    # no longer called by `standard_run`. See `TODO.md`.
    landing_backend: Literal["s3", "postgres", "mongodb"] = "mongodb"

    # DuckDB raw-landing staging (`overview.md` §1 Storage — "no MongoDB,
    # no MinIO/S3 dependency is needed for this staging layer"). One
    # embedded, file-backed `.duckdb` file per ingest run, named by run id,
    # under this directory — `pipeline.duckdb_staging.stage_dataframe`.
    # One file per run (not one shared file) deliberately: DuckDB only
    # supports a single read-write connection to a given file at a time,
    # so sharing one file between the short-lived ingest process (writer)
    # and the long-running warehouse-sync consumer (reader, then deleter)
    # would mean fighting over that lock. Per-run files sidestep it
    # entirely — the ingest side always closes its connection (and the
    # RabbitMQ event only fires after that close) before the consumer
    # ever opens the file.
    duckdb_staging_dir: str = "./data/staging"

    # RabbitMQ (`overview.md` §2 Event-Driven Warehousing). Decouples
    # ingestion (stages in DuckDB, publishes one message here) from
    # warehousing (consumes the message, syncs DuckDB -> Postgres `raw.*`)
    # — see `app.db.rabbitmq`, `app.service.pipeline.warehouse_sync`,
    # and the `ecolens-pipeline worker` CLI command / `warehouse-sync`
    # docker-compose service that runs the consumer loop.
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_landing_queue: str = "ecolens.landing"

    # Training-trigger event queue (`TODO.md`'s "Event-Driven Pipeline
    # Trigger for Online/Incremental Model Training"). Decouples "the
    # warehouse just finished a dbt build" (`pipeline.flows.daily_demand`'s
    # `publish_training_trigger` task) from "run an incremental training
    # pass" (`ecolens-pipeline train-worker` / `app.service.training_worker`),
    # the same producer/consumer split `rabbitmq_landing_queue` already
    # uses for ingestion -> warehousing. Unlike that queue, this one has a
    # real dead-letter exchange (`mq.rabbitmq_client`'s topology) — a
    # malformed/repeatedly-failing training-trigger event lands in
    # `rabbitmq_training_trigger_dlq` instead of vanishing (a bad ingest
    # event just gets logged as `sync_failed` and retried from the
    # DuckDB file; a training-trigger event has no equivalent on-disk
    # recovery artifact, so it needs the DLQ to not silently disappear).
    rabbitmq_training_exchange: str = "forecasting.training"
    rabbitmq_training_routing_key: str = "training.trigger"
    rabbitmq_training_trigger_queue: str = "forecasting.training.trigger"
    rabbitmq_training_dlx: str = "forecasting.training.dlx"
    rabbitmq_training_trigger_dlq: str = "forecasting.training.trigger.dlq"

    # Incremental (warm-started) training tunables -- `ml/incremental.py`.
    # Deliberately much lighter than `model_train_epochs`/`model_train_lr`'s
    # from-scratch defaults (50 epochs, lr=1e-3): a fine-tune that starts
    # from an existing Production/Staging version's weights needs far
    # fewer steps and a smaller learning rate to adapt to a small recent
    # data window without overwriting what the full retrain already
    # learned (`TODO.md`'s "balancing plasticity and stability").
    incremental_train_epochs: int = 3
    incremental_train_lr: float = 1e-4
    incremental_train_window_hours: int = 24

    # MLflow tracking (README § Quickstart: `mlflow -> http://localhost:5000`).
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_registry_model_name: str = "lstm_demand"

    # OpenElectricity (ECO-D23). Free tier works with a registered key;
    # None means anonymous/rate-limited access.
    oe_api_key: str | None = None

    # BoM weather stations (README § Data sources -> BoM), region -> BoM
    # station number. One entry per NEM region + WEM; the numbers are the
    # capital-city-airport stations (ECO-D28) — real, public BoM station
    # IDs, but not verified against BoM's current JSON API URL scheme.
    bom_api_key: str | None = None
    bom_stations: dict[str, str] = {
        "NSW1": "066037",  # Sydney Airport
        "QLD1": "040913",  # Brisbane Airport
        "VIC1": "086282",  # Melbourne Airport
        "SA1": "023034",  # Adelaide Airport
        "TAS1": "094029",  # Hobart Airport
        "WEM": "009225",  # Perth Airport
    }
    bom_request_timeout_seconds: float = 10.0

    # AEMO (ECO-D26/D27).
    aemo_request_timeout_seconds: float = 10.0

    # Shared ingest fallback (ECO-D24): how far back to look when a task's
    # `lookback_minutes` isn't given explicitly by the caller.
    default_lookback_minutes: int = 30

    # CircuitBreaker (ECO-D07/D70). Applied uniformly to every source via
    # redis_client.get_breaker() — task.md's recovery playbook tunes
    # these globally for a known-flaky upstream (not per-source; if one
    # source needs a different threshold than the rest, that's a bigger
    # change than this ticket scoped).
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_reset_timeout: float = 60.0

    # ML training tunables (README § ML pipeline -> Demand forecasting).
    model_train_epochs: int = 50
    model_train_lr: float = 1e-3
    model_hidden_size: int = 128
    model_dropout: float = 0.2
    model_num_layers: int = 2
    model_lookback: int = 48
    model_horizon: int = 48
    model_batch_size: int = 64
    model_quantile_weight: float = 1.0
    model_early_stopping_patience: int = 5
    # `ml/conformal.py`'s target miscoverage -- 0.2 -> an 80% (P10-P90)
    # interval, matching DemandLSTM's two quantile heads.
    conformal_alpha: float = 0.2
    # Fraction of the (already time-split) validation set reserved for
    # conformal calibration rather than early-stopping -- see
    # `ml/train.py`'s docstring for why these must be disjoint.
    model_cal_frac: float = 0.5
    # Regions `make train`/`ecolens-pipeline train` trains across when no
    # `--region` is passed. README's Roadmap stages NSW1 first
    # ("Baseline LSTM v0 (NSW1)") before the other NEM regions + WEM.
    model_default_regions: list[str] = ["NSW1"]

    # dbt (README's data-pipeline tree; ECO-D21/D22).
    dbt_project_dir: str = "dbt/ecolens"
    dbt_target: str = "prod"

    # JWT bearer auth (API_SPECEFICATIONS.md § Conventions: `Auth | JWT
    # bearer (admin or analyst)`). HS256 shared secret, verified by
    # `app.core.security`. `POST /v1/auth/token` (`app.service.auth`) is
    # this service's own real token issuer for admin/automation callers
    # (`meta.api_users`) — that domain stays exactly as it was.
    jwt_secret: str = "dev-secret-change-me-32-bytes-min"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expires_seconds: int = 3600

    # IAM token bridge: `get_current_principal` also accepts a bearer
    # token signed with THIS secret (IAM's own `SECRET_KEY`/`ALGORITHM`,
    # see services/iam/app/core/config.py) as a second, independent
    # trust anchor — not by replacing `jwt_secret` above with IAM's, so
    # this service's own self-issued tokens (`meta.api_users`) keep
    # working unchanged even if IAM's secret ever rotates, and vice
    # versa. Lets the dashboard's existing IAM session directly call
    # admin-gated data-pipeline routes (e.g. triggering an ingestion
    # run) without a second login — IAM's access token now carries a
    # `role` claim for exactly this (`is_superuser` -> admin/analyst;
    # see services/iam's `_mint_access_token`). `None` (the default)
    # disables the bridge entirely — an IAM-signed token is then just
    # an unverifiable signature, same as any other invalid token.
    iam_jwt_secret: str | None = None
    iam_jwt_algorithm: str = "HS256"

    # Redis token-bucket rate limiting (`README.md`: "60 req/min per
    # token"; `app.core.ratelimit`). Applied per authenticated caller
    # (JWT `sub`) for the general API, and separately (stricter, per
    # client IP -- there's no token yet at that point) for
    # `POST /v1/auth/token` itself, since a bare login endpoint is
    # exactly what credential-stuffing/brute-force targets.
    rate_limit_requests_per_minute: int = 60
    rate_limit_login_attempts_per_minute: int = 10

    # Recorded on every meta._ingest_log row (ECO-D24) so a multi-runner
    # setup (several GitHub Actions runners, or API + cron on a VPS) can
    # tell which process ran a given ingest.
    hostname: str = Field(default_factory=socket.gethostname)

    @property
    def database_url(self) -> str:
        """`postgresql+asyncpg://` DSN for SQLAlchemy's async engine (ECO-D05).

        Uses `DATABASE_URL` verbatim if set, else assembles one from the
        decomposed `postgres_*` fields. Two normalizations applied to the
        `DATABASE_URL` case: a plain `postgresql://` scheme becomes
        `+asyncpg`, and `sslmode=` (libpq/psycopg's query-param name,
        what Neon and most providers hand you) becomes `ssl=` (what
        asyncpg actually understands — the *values* like `require` are
        compatible, only the key differs). Without this, a real
        `DATABASE_URL` from Neon connects fine via `psql`/psycopg but
        fails via asyncpg with `connect() got an unexpected keyword
        argument 'sslmode'`.
        """
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
        """`redis://` DSN for the async Redis client (ECO-D06).

        Uses `REDIS_URL` verbatim if set, else assembles one from the
        decomposed `redis_*` fields.
        """
        if self.redis_url_env:
            return self.redis_url_env
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
