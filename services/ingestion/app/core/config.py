"""ecoLens ingestion service configuration.

Single source of truth for runtime settings — a deliberate *subset* of
`data-pipeline`'s `Settings` (see `services/ingestion/TODO.md` Phase 0's
"scoped configuration" decision): this service owns Postgres access only
for `meta._ingest_log` writes (never `raw.*` — that stays warehouse's
job), Redis for circuit-breaker state, RabbitMQ for publishing landed
events (never consuming), DuckDB staging, and the 5 sources' own fetch
settings. Everything MLflow/ML/dbt-related is deliberately absent — this
service never touches any of that.
"""

from __future__ import annotations

import socket
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# This file lives at services/ingestion/app/core/config.py -- three
# `.parent`s up is services/ingestion itself, where `.env` lives. Anchoring
# `env_file` here (not a bare relative string) makes it independent of the
# invoking process's CWD -- same reasoning as data-pipeline's identical
# `_PACKAGE_ROOT` (that service's `config.py` docstring covers the exact
# silent-wrong-.env failure mode this avoids).
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Ingestion service runtime settings.

    All fields are loaded from environment variables. The service
    container supplies them via docker-compose's `env_file: .env`.
    """

    model_config = SettingsConfigDict(
        env_file=str(_PACKAGE_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API — this service's own FastAPI control plane.
    api_port: int = 8003
    api_cors_origins: list[str] = ["*"]

    database_url_env: str | None = Field(default=None, validation_alias="DATABASE_URL")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ecolens"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

    # Redis — circuit-breaker state (Phase 1) + the backfill lock. Same
    # shared instance data-pipeline uses today.
    redis_url_env: str | None = Field(default=None, validation_alias="REDIS_URL")
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # RabbitMQ — publish-only (Phase 1's `publish_landed_event`). This
    # service never consumes; `consume_landed_events`/`warehouse_sync`
    # stay in `data-pipeline`.
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_landing_queue: str = "ecolens.landing"
    # Phase 4's "Execute Shadow Runs" -- a `triggered_by="shadow"` run
    # (`pipeline.tasks._common.standard_run`) publishes here instead of
    # the real landing queue above, so whichever service still runs
    # `pipeline.warehouse_sync`'s consumer never picks it up and
    # double-loads `raw.*` from two independent fetches of the same
    # upstream window. A shadow run still does everything else for
    # real (fetch, anomaly-scan, stage, `meta._ingest_log` row) -- only
    # the publish target differs, so `scripts/verify_shadow_parity.py`
    # can compare it against a real run's outcome.
    rabbitmq_landing_queue_shadow: str = "ecolens.landing.shadow"

    # DuckDB staging directory (Phase 1) -- holds a single shared
    # `landed.duckdb` file (2026-08-05 decision: was one file per run;
    # see `pipeline.duckdb_staging`'s own module docstring for the full
    # reasoning and the tradeoff it accepts). Every ingest run appends
    # into it. Still written to local disk (Phase 2's "Bridge Legacy
    # Handoffs" -- data-pipeline's warehouse_sync consumer still reads
    # this shared volume during the transition, though its `read_staged`/
    # `delete_staged` call shape changed and needs a matching update)
    # *and*, since Phase 2, each run's own rows are also extracted and
    # uploaded to object storage under `object_storage_staging_prefix`
    # -- see `pipeline.duckdb_staging.upload_staged_file`.
    duckdb_staging_dir: str = "./data/staging"

    # Cloudflare R2 (S3-compatible) -- same account/bucket data-pipeline's
    # own `object_storage.py` uses for dashboard assets/MLflow artifacts,
    # this service just uploads staged run files under a different key
    # prefix (`object_storage_staging_prefix`) rather than a separate
    # bucket. Falls back to local MinIO (`s3_*` below) when unset, same
    # "real value overrides local default" shape as `database_url`.
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "ecolens"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    object_storage_staging_prefix: str = "staging"

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

    # Circuit breaker (Phase 1) -- same defaults as data-pipeline's
    # `CircuitBreaker` (`pipeline/circuit_breaker.py`'s own defaults),
    # duplicated here rather than imported since this service doesn't
    # depend on data-pipeline's package at all.
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_reset_timeout: float = 60.0

    # Per-source fetch settings (Phase 1) -- same values/defaults as
    # data-pipeline's `Settings`, so porting the 5 ingest tasks verbatim
    # doesn't require touching their config lookups.
    oe_api_key: str | None = None
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
    aemo_request_timeout_seconds: float = 10.0
    default_lookback_minutes: int = 30

    # `app.core.response_cache` (2026-08-11, real fix for several
    # endpoints confirmed live at 2-4s/call with no caching at all --
    # not per-endpoint compute, just this service's own real Postgres
    # round-trip cost paid fresh on every request). Short (5s): these
    # back live status polling (backfill/run progress, `pollBackfill
    # Summary`'s own 3s client poll interval) -- a bounded few-second
    # staleness window is a real, disclosed tradeoff for guaranteeing a
    # fast response, not fabricated data.
    public_status_cache_ttl_seconds: int = 5
    # Feature-selection results change only when a rebuild completes
    # (minutes-to-hours apart in practice, not seconds) -- safe to cache
    # much longer than the live-status endpoints above.
    feature_rebuild_runs_cache_ttl_seconds: int = 60

    # JWT bearer auth, verification-only (`app.core.security`) -- this
    # service never issues tokens (no `meta.api_users`/`POST /v1/auth/
    # token` here, unlike data-pipeline): it only verifies tokens someone
    # else issued, against either this same shared `jwt_secret` (set it
    # to data-pipeline's real value to accept its self-issued tokens
    # too) or IAM's `iam_jwt_secret`. Gates the admin-only `GET`/`PATCH
    # /v1/data-sources[/{id}]`/`.../health`/`.../history` endpoints
    # (`services/ingestion/TODO.md` Phase 1's "Expose CLI & API
    # Routers" scope decision -- trigger endpoints stay open, these
    # don't).
    jwt_secret: str = "dev-secret-change-me-32-bytes-min"
    jwt_algorithm: str = "HS256"
    iam_jwt_secret: str | None = None
    iam_jwt_algorithm: str = "HS256"

    # Redis token-bucket rate limiting (`app.core.ratelimit`), applied
    # per authenticated caller (JWT `sub`) to the admin-gated endpoints
    # above. Same default as data-pipeline's identical field.
    rate_limit_requests_per_minute: int = 60

    # Recorded on every meta._ingest_log row, same as data-pipeline's
    # identical field -- lets an operator tell which process/host ran a
    # given ingest, now meaningful across two separate services instead
    # of just multiple runners of one.
    hostname: str = Field(default_factory=socket.gethostname)

    # `TODO.md` Observability Phase 1's "OpenTelemetry Core SDK
    # Integration" -- same real-no-op-when-disabled pattern
    # `services/waerehouse`/`services/forecast-api`'s identical settings
    # use; exports to `services/observility`'s already-configured
    # Collector when enabled, never straight to Tempo.
    otel_traces_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    # Bound as a static field on every log line (`core/logging.py`) --
    # matches `services/observility/prometheus/prometheus.yml.template`'s
    # own hardcoded `external_labels.environment: development` default.
    environment: str = "development"

    @property
    def database_url(self) -> str:
        """`postgresql+asyncpg://` DSN for SQLAlchemy's async engine.

        Uses `DATABASE_URL` verbatim if set, else assembles one from the
        decomposed `postgres_*` fields. Same two normalizations as
        data-pipeline's identical property: a plain `postgresql://`
        scheme becomes `+asyncpg`, and `sslmode=` (what Neon/most
        providers hand you) becomes `ssl=` (what asyncpg understands).
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
        decomposed `redis_*` fields.
        """
        if self.redis_url_env:
            return self.redis_url_env
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

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
        (`s3_endpoint_url`). `r2_s3_api_env` as issued for this project
        already has the bucket name appended as a path segment
        (`https://<account>.r2.cloudflarestorage.com/<bucket>`) — S3
        clients take `Bucket=` as a separate call parameter, not part of
        the endpoint URL, so this strips back to a bare origin rather than
        assume every future R2 token looks the same shape."""
        if self.object_storage_configured and self.r2_s3_api_env:
            parsed = urlparse(self.r2_s3_api_env)
            return f"{parsed.scheme}://{parsed.netloc}"
        if self.object_storage_configured and self.r2_account_id:
            return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
        return self.s3_endpoint_url

    @property
    def object_storage_bucket(self) -> str:
        """Bucket name parsed off `r2_s3_api_env`'s path suffix once R2 is
        configured, else local MinIO's `s3_bucket`."""
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
