"""ecoLens warehouse service configuration.

Single source of truth for runtime settings — this service owns the
consumer side of the event-driven warehousing pipeline (`overview.md`
§2): it reads `ecolens.landing` off RabbitMQ (the same queue `services/
ingestion`'s `publish_landed_event` writes to — the queue *name* has to
match exactly, it's the one real coupling point between the two
services), reads the shared DuckDB staging file `services/ingestion`
writes into, loads into Postgres `raw.*`, enforces the free-tier
rolling-window retention policy, and runs dbt on top. Never fetches from
external providers or writes to `meta._ingest_log` — that's ingestion's
job (`services/ingestion/TODO.md`'s own service-boundary note).
"""

from __future__ import annotations

import socket
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# This file lives at services/waerehouse/app/core/config.py -- three
# `.parent`s up is services/waerehouse itself, where `.env` lives.
# Anchoring `env_file` here (not a bare relative string) makes it
# independent of the invoking process's CWD -- same reasoning as
# ingestion/data-pipeline's identical `_PACKAGE_ROOT`.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Warehouse service runtime settings.

    All fields are loaded from environment variables. The service
    container supplies them via docker-compose's `env_file: .env`.
    """

    model_config = SettingsConfigDict(
        env_file=str(_PACKAGE_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API -- this service's own FastAPI control plane (Phase 5).
    api_port: int = 8004
    api_cors_origins: list[str] = ["*"]

    database_url_env: str | None = Field(default=None, validation_alias="DATABASE_URL")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ecolens"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

    # Second physical database (root TODO.md's "save raw and raw.marts
    # in seperate database" -- a separate Neon project, not a schema on
    # the same one). `app/retention/marts_archive.py` is the only thing
    # that ever connects to it: `raw_marts.*`'s permanent, unbounded
    # archive lives here, while the primary database keeps a rolling
    # window of the same tables (`marts_local_retention_days`) for live
    # queries. Optional -- unset means the archive task no-ops (same
    # "optional infra" convention `object_storage_configured` already
    # uses), not a hard failure.
    raw_marts_database_url_env: str | None = Field(
        default=None, validation_alias="RAW_MARTS_DATABASE_URL"
    )

    # Third, separate Postgres instance (2026-08-12) for the real
    # "logger" tables (`meta._ingest_log` -- this service's own status-
    # update side, `app/loaders/ingest_log.py`; `meta._dbt_build_log`,
    # `meta._retention_log`, `meta._marts_archive_log`) -- an explicit
    # split from `DATABASE_URL` for the same reason `RAW_MARTS_DATABASE_URL`
    # above is its own separate database, just for audit/history tables
    # instead of `raw_marts.*`. Falls back to `database_url` when unset.
    # **Must be the identical value `services/ingestion` and `services/
    # forecast-api` use** -- `meta.anomalies.run_id` has a real foreign
    # key into `meta._ingest_log(id)`, so those two tables (and by
    # extension, every service that touches either) can never point at
    # different physical databases from each other.
    log_db_url_env: str | None = Field(default=None, validation_alias="LOG_DB_URL")

    # Redis -- new 2026-08-11 (`app.core.response_cache`), this service
    # previously had no caching layer at all (RabbitMQ-only, unlike
    # `services/ingestion`'s Redis-backed circuit breaker/backfill lock).
    # Same shared local instance the other two services already use, same
    # decomposed-fields-with-URL-override shape as `database_url` below.
    redis_url_env: str | None = Field(default=None, validation_alias="REDIS_URL")
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # How long `raw_marts.*` rows stay in the *primary* database before
    # being archived to `raw_marts_database_url` and pruned. Defaults to
    # `retention_days` for consistency with `raw.*`'s own window, but
    # kept as its own field since marts rows are much smaller
    # individually (aggregated, not raw per-reading) -- an operator may
    # reasonably want to keep more days of marts locally than raw.
    marts_local_retention_days: int = 60

    # `app.core.response_cache` (2026-08-11, real fix: `GET /v1/dbt/
    # build/last`/`/build/runs` confirmed live at ~2.3-2.7s/call with no
    # caching at all -- this service's own real Postgres round-trip
    # cost, not per-endpoint compute). Short: these back the dashboard's
    # live dbt-build-status polling -- a bounded few-second staleness
    # window is a real, disclosed tradeoff for a fast response, not
    # fabricated data.
    dbt_build_status_cache_ttl_seconds: int = 5

    # RabbitMQ (Phase 1's "RabbitMQ Consumer Framework") -- consume-only,
    # the mirror image of ingestion's publish-only `rabbitmq_url`/
    # `rabbitmq_landing_queue`. `rabbitmq_landing_dlx`/`_dlq` are new
    # here -- `data-pipeline`'s current landing queue has no DLX at all
    # (confirmed by reading `app/db/rabbitmq.py` there); this service's
    # consumer adds one (README Phase 1's explicit ask), following the
    # same topology shape that codebase's own training-trigger queue
    # already uses.
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_landing_queue: str = "ecolens.landing"
    rabbitmq_landing_dlx: str = "ecolens.landing.dlx"
    rabbitmq_landing_dlq: str = "ecolens.landing.dlq"

    # Training-trigger topology (publish-only here) -- this service now
    # owns the real dbt build (`POST /v1/dbt/build`), so it's the one
    # that fires the "warehouse transform completed, incremental
    # training may run" event `forecast-api`'s `training_worker`
    # consumes, same names/topology data-pipeline's identical
    # `app/db/rabbitmq.py` used (the queue names are the one real
    # coupling point with the consumer side, now in forecast-api).
    rabbitmq_training_exchange: str = "forecasting.training"
    rabbitmq_training_routing_key: str = "training.trigger"
    rabbitmq_training_trigger_queue: str = "forecasting.training.trigger"
    rabbitmq_training_dlx: str = "forecasting.training.dlx"
    rabbitmq_training_trigger_dlq: str = "forecasting.training.trigger.dlq"

    # Same defaults as forecast-api's identical fields (`incremental.py`'s
    # window, `train`/`train-tft`'s default region set) -- this service
    # builds the training-trigger payload but never trains, so it only
    # needs these two to fill in the payload when a caller doesn't
    # override them.
    #
    # Real bug, confirmed live 2026-08-12: this was left at `["NSW1"]`
    # while forecast-api's identical field default is all 6 real regions
    # -- despite this field's own docstring above already claiming "same
    # defaults as forecast-api's identical fields". Every automatic
    # post-landed-event training trigger (`dbt.training_trigger.publish_
    # training_triggers_for_build`, which fills in this default whenever
    # a caller doesn't override it -- and the real landed-event path
    # never does) has only ever fine-tuned NSW1 as a result; QLD1/VIC1/
    # SA1/TAS1/WEM never received an automatic incremental fine-tune.
    model_default_regions: list[str] = ["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"]
    # Real bug, confirmed live 2026-08-11 (see forecast-api's identical
    # field for the full math): 24h guaranteed forecast-api's
    # `train_model` "not enough history" error for every real automatic
    # post-dbt-build trigger this service ever published -- kept in sync
    # with forecast-api's own fix (336h/14 days) per this field's own
    # "same defaults" docstring above.
    incremental_train_window_hours: int = 336

    # DuckDB staging directory -- the SAME shared `landed.duckdb` file
    # `services/ingestion` writes into (its own `Settings.
    # duckdb_staging_dir` docstring covers the full reasoning). This
    # service only ever opens it read-only. Default matches ingestion's
    # own default exactly, deliberately -- in Docker both containers
    # mount the same named `duckdb_staging` volume at `<their own
    # WORKDIR>/data/staging`, so identical *relative* defaults resolve
    # to the same physical file from each container's own root (verified
    # live, `services/ingestion/TODO.md`'s Storage section has the full
    # story) -- change this only in lockstep with ingestion's own.
    duckdb_staging_dir: str = "./data/staging"

    # Cloudflare R2 (S3-compatible) -- same account/bucket ingestion's
    # own `object_storage.py` uses, this service's own cold-storage
    # export (Phase 3) writes under a different key prefix
    # (`object_storage_coldstorage_prefix`) rather than a separate
    # bucket. Falls back to local MinIO (`s3_*` below) when unset, same
    # "real value overrides local default" shape as `database_url`.
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "ecolens"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    object_storage_coldstorage_prefix: str = "coldstorage"

    r2_account_id: str | None = Field(
        default=None, validation_alias="CLOUDFLARESTORAGE_ACCOUNT_ID"
    )
    r2_s3_api_env: str | None = Field(
        default=None, validation_alias="CLOUDFLARESTORAGE_S3_API"
    )
    r2_access_key_id: str | None = Field(
        default=None, validation_alias="CLOUDFLARESTORAGE_ACCESS_KEY_ID"
    )
    r2_secret_access_key: str | None = Field(
        default=None, validation_alias="CLOUDFLARESTORAGE_SECRET_ACCESS_KEY"
    )

    # Rolling-window retention (Phase 3 -- "Critical for Free Tier").
    # README's own example: "DELETE FROM raw.telemetry WHERE timestamp <
    # NOW() - INTERVAL '2 months'" -- 60 days is that window in plain
    # day-count form (easier to reason about/test than a variable-length
    # calendar month).
    retention_days: int = 60

    # NeonDB's free-tier project storage cap (README Phase 3's own
    # number). `retention_warning_pct` is when monitoring should start
    # alerting; `retention_emergency_pct` is when an out-of-band
    # emergency prune (tighter than `retention_days`) should trigger --
    # both against this same limit.
    database_size_limit_mb: int = 500
    retention_warning_pct: float = 0.80
    retention_emergency_pct: float = 0.95

    # dbt project (Phase 4) -- ported from data-pipeline's `dbt/ecolens`
    # (`services/waerehouse/dbt/ecolens`), pointed at this service's own
    # `DATABASE_URL` via `profiles.yml`'s env var indirection, same
    # target database/schema, now run from here rather than data-pipeline.
    # A bare relative default here would resolve against whatever the
    # invoking process's CWD happens to be, not this package's own root
    # -- the exact class of bug `services/ingestion`'s `duckdb_staging_
    # dir` hit earlier this session. `dbt_project_dir` (the property
    # below) is what callers should actually use.
    dbt_project_dir_env: str = Field(
        default="dbt/ecolens", validation_alias="DBT_PROJECT_DIR"
    )

    # `TODO.md`'s "Scheduled Execution Runner" -- how often a real landed
    # event (`consumers.landed_events.sync_landed_event`) is allowed to
    # trigger an automatic `dbt build`, at most. Not "build after every
    # single landed event" -- 5 sources landing independently within the
    # same ingestion cycle would mean up to 5 builds back to back for no
    # real benefit (a dbt build already processes everything currently in
    # `raw.*`, not just the one just-landed row). 15 minutes is tighter
    # than ingestion's own 30-minute Celery Beat cadence, so a build is
    # never more than one ingestion cycle stale, without triggering more
    # than ~2x as often as new data can actually arrive.
    scheduled_build_min_interval_minutes: int = 15

    # `TODO.md` Phase 6's "OpenTelemetry Tracing" -- `services/observility`'s
    # OTel Collector already accepts OTLP grpc on this exact port
    # (`otel-collector-config.yml`'s `otlp.protocols.grpc` receiver,
    # `docker-compose.yml`'s `4317:4317`); this is that collector's
    # address, not a direct-to-Tempo export (batching/buffering happens
    # at the collector, not in this service, per that stack's own
    # "Avoiding Observability Spam" design principle). `otel_traces_enabled`
    # defaults `False` -- tracing is opt-in until an operator actually
    # has the collector running; `configure_tracing()` is a real no-op
    # otherwise; matches this project's pattern of never assuming
    # optional infra is present (e.g. `object_storage_configured`).
    otel_traces_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    # Bound as a static field on every log line (`core/logging.py`) --
    # matches `services/observility/prometheus/prometheus.yml.template`'s
    # own hardcoded `external_labels.environment: development` default.
    environment: str = "development"

    # Recorded in structured logs -- lets an operator tell which
    # process/host ran a given consume/retention/dbt job, same role
    # ingestion/data-pipeline's identical `hostname` field plays.
    hostname: str = Field(default_factory=socket.gethostname)

    @property
    def database_url(self) -> str:
        """`postgresql+asyncpg://` DSN for SQLAlchemy's async engine.

        Uses `DATABASE_URL` verbatim if set, else assembles one from the
        decomposed `postgres_*` fields. Same two normalizations as
        ingestion/data-pipeline's identical property: a plain
        `postgresql://` scheme becomes `+asyncpg`, and `sslmode=` (what
        Neon/most providers hand you) becomes `ssl=` (what asyncpg
        understands).
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
        """`redis://` DSN for the async Redis client.

        Uses `REDIS_URL` verbatim if set, else assembles one from the
        decomposed `redis_*` fields -- same shape as `database_url` above
        and as `services/ingestion`'s identical property.
        """
        if self.redis_url_env:
            return self.redis_url_env
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def log_db_url(self) -> str:
        """`postgresql+asyncpg://` DSN for the separate logging database
        (`db.session.get_log_engine`) -- uses `LOG_DB_URL` verbatim (same
        normalization as `database_url`) if set, else falls back to
        `database_url` itself so an unconfigured deployment keeps writing
        logs to the primary database exactly as it always did."""
        if self.log_db_url_env:
            url = self.log_db_url_env
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            url = url.replace("sslmode=", "ssl=")
            return url
        return self.database_url

    @property
    def raw_marts_archive_configured(self) -> bool:
        """True once a real second-database URL is set. Same shape as
        `object_storage_configured` -- the archive task checks this and
        no-ops rather than failing when unconfigured."""
        return bool(self.raw_marts_database_url_env)

    @property
    def raw_marts_database_url(self) -> str:
        """`postgresql+asyncpg://` DSN for the second database -- same
        two normalizations `database_url` applies. Only call this after
        checking `raw_marts_archive_configured`; raises if unset rather
        than silently falling back to the primary database (archiving a
        table to itself would be a real, silent no-op bug, not a safe
        default)."""
        if not self.raw_marts_database_url_env:
            raise RuntimeError(
                "RAW_MARTS_DATABASE_URL is not configured -- check "
                "raw_marts_archive_configured before calling this"
            )
        url = self.raw_marts_database_url_env
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        url = url.replace("sslmode=", "ssl=")
        return url

    @property
    def dbt_project_dir(self) -> str:
        """`dbt_project_dir_env` resolved against this package's own
        root if it's a relative path -- so `dbt.runner.run_dbt` finds
        the real project regardless of the invoking process's CWD."""
        path = Path(self.dbt_project_dir_env)
        if not path.is_absolute():
            path = _PACKAGE_ROOT / path
        return str(path)

    @property
    def dbt_postgres_env(self) -> dict[str, str]:
        """`POSTGRES_HOST`/`PORT`/`USER`/`PASSWORD`/`DB` derived from
        `database_url` -- what `dbt/ecolens/profiles.yml` actually needs.

        dbt reads these as raw OS environment variables via Jinja
        `env_var()` (`app.dbt.runner.run_dbt`'s subprocess), a completely
        separate resolution path from this class's own `DATABASE_URL`-
        first logic above. Without this, a NeonDB (or any other
        single-DSN) deployment that only sets `DATABASE_URL` -- the
        normal case everywhere else in this app -- leaves dbt's profile
        vars unset, and dbt silently falls back to *its own* defaults
        instead of raising: a `dbt build` that runs, exits 0, and
        rebuilds nothing in the real database. Ported from `data-
        pipeline`'s identical property -- same real bug it was written
        to avoid.
        """
        parsed = urlparse(
            self.database_url.replace("postgresql+asyncpg://", "postgresql://")
        )
        return {
            "POSTGRES_HOST": parsed.hostname or "localhost",
            "POSTGRES_PORT": str(parsed.port or 5432),
            "POSTGRES_USER": parsed.username or "postgres",
            "POSTGRES_PASSWORD": parsed.password or "postgres",
            "POSTGRES_DB": parsed.path.lstrip("/") or "ecolens",
        }

    @property
    def object_storage_configured(self) -> bool:
        """True once a real R2 API token is present. `r2_s3_api_env`/
        `r2_account_id` alone (Cloudflare hands these out even before a
        token is generated) aren't enough to authenticate — both the
        access key id and secret are required."""
        return bool(self.r2_access_key_id and self.r2_secret_access_key)

    @property
    def object_storage_endpoint_url(self) -> str:
        """R2's S3-compatible endpoint once configured, else local MinIO
        (`s3_endpoint_url`)."""
        if self.object_storage_configured and self.r2_s3_api_env:
            parsed = urlparse(self.r2_s3_api_env)
            return f"{parsed.scheme}://{parsed.netloc}"
        if self.object_storage_configured and self.r2_account_id:
            return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
        return self.s3_endpoint_url

    @property
    def object_storage_bucket(self) -> str:
        """Bucket name parsed off `r2_s3_api_env`'s path suffix once R2
        is configured, else local MinIO's `s3_bucket`."""
        if self.object_storage_configured and self.r2_s3_api_env:
            path_bucket = urlparse(self.r2_s3_api_env).path.strip("/")
            if path_bucket:
                return path_bucket
        return self.s3_bucket

    @property
    def object_storage_access_key(self) -> str:
        if self.object_storage_configured:
            assert self.r2_access_key_id is not None  # nosec B101 -- internal invariant for type-narrowing, not a security check; object_storage_configured guarantees this
            return self.r2_access_key_id
        return self.s3_access_key

    @property
    def object_storage_secret_key(self) -> str:
        if self.object_storage_configured:
            assert self.r2_secret_access_key is not None  # nosec B101 -- internal invariant for type-narrowing, not a security check; object_storage_configured guarantees this
            return self.r2_secret_access_key
        return self.s3_secret_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
