"""MongoDB-specific settings for the ingestion layer.

File path:
    services/data-pipeline/src/ecolens/ingestion/storage/settings.py

Why a separate file?
    * Keeps MongoDB tunables together (URI, pool sizes, timeouts, retry policy).
    * Lets the ingestion layer override defaults without touching the global
      `ecolens.config.Settings` (which holds every other service's config).

The `mongo.py` module reads from these settings. End-users can override any
field via environment variables (e.g. `MONGO_URI`, `MONGO_MAX_POOL_SIZE`).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MongoSettings(BaseSettings):
    """MongoDB client + collection configuration.

    Independent of the global `Settings` class so the ingestion layer can
    be deployed with its own tuning (e.g. a higher pool size for a busy
    pipeline) without affecting the rest of the service.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Connection ──────────────────────────────────────────────────────
    mongo_uri: str = Field(
        default="mongodb://mongo:27017",
        description="MongoDB connection string. Include credentials in the URI.",
    )
    mongo_db_name: str = Field(
        default="ecolens",
        description="Default database. All collections live under this name.",
    )
    mongo_auth_source: str = Field(
        default="admin",
        description="Auth source for the user. Usually 'admin' or the db name.",
    )

    # ── Pool sizing ─────────────────────────────────────────────────────
    mongo_max_pool_size: int = Field(
        default=20,
        ge=1,
        le=1000,
        description="Max concurrent connections in the pool.",
    )
    mongo_min_pool_size: int = Field(
        default=5,
        ge=0,
        le=1000,
        description="Connections kept warm even when idle.",
    )

    # ── Timeouts (milliseconds) ─────────────────────────────────────────
    mongo_server_selection_timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60_000,
        description="How long to wait for a server to become available.",
    )
    mongo_connect_timeout_ms: int = Field(
        default=10_000,
        ge=100,
        le=60_000,
        description="TCP connect timeout.",
    )
    mongo_socket_timeout_ms: int = Field(
        default=30_000,
        ge=1000,
        le=300_000,
        description="Socket-level read/write timeout.",
    )
    mongo_wait_queue_timeout_ms: int = Field(
        default=10_000,
        ge=100,
        le=60_000,
        description="How long a request waits for a free connection.",
    )

    # ── Retry policy ────────────────────────────────────────────────────
    mongo_retry_reads: bool = Field(
        default=True,
        description="Retry reads on transient network errors.",
    )
    mongo_retry_writes: bool = Field(
        default=True,
        description="Retry writes on transient network errors (requires a replica set).",
    )

    # ── Write concern ───────────────────────────────────────────────────
    mongo_write_concern_w: Literal["majority", 1, 0] = Field(
        default="majority",
        description=(
            "Write concern for ingestion writes. 'majority' is the safe "
            "default; use 1 for higher throughput when you can tolerate data loss."
        ),
    )
    mongo_read_preference: Literal[
        "primary", "primaryPreferred", "secondary", "nearest"
    ] = Field(
        default="primary",
        description="Read preference. 'primary' for the ingestion path.",
    )

    # ── Bulk write tunables ─────────────────────────────────────────────
    mongo_bulk_chunk_size: int = Field(
        default=1000,
        ge=10,
        le=10_000,
        description="How many docs per bulk_write call. Large chunks are faster but use more memory.",
    )
    mongo_bulk_ordered: bool = Field(
        default=False,
        description="False = continue on errors (faster, more resilient). True = stop on first error.",
    )

    # ── Collection names (centralised, easy to override) ────────────────
    coll_openelectricity: str = "openelectricity_responses"
    coll_aemo_nem: str = "aemo_nem_dispatch"
    coll_aemo_wem: str = "aemo_wem_dispatch"
    coll_bom: str = "bom_observations"
    coll_aemo_holidays: str = "aemo_holidays"
    coll_meta_ingest_runs: str = "meta_ingest_runs"

    # ── Ingest tunables (related to the MongoDB path) ──────────────────
    ingest_concurrent_sources: int = Field(
        default=4,
        ge=1,
        le=20,
        description="How many sources run concurrently in ingest_all().",
    )
    ingest_concurrent_requests_per_source: int = Field(
        default=6,
        ge=1,
        le=50,
        description="Per-source concurrency (e.g. one request per region in parallel).",
    )
    ingest_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="How many times to retry a failed HTTP request.",
    )
    ingest_retry_backoff_base: float = Field(
        default=1.5,
        ge=1.0,
        le=10.0,
        description="Exponential backoff base. Delay = base ** attempt.",
    )
    ingest_circuit_breaker_threshold: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Failures before the per-source breaker opens.",
    )
    ingest_circuit_breaker_timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="How long the breaker stays open before half_open.",
    )

    # ── Helpers ────────────────────────────────────────────────────────
    def collection_for_source(self, source: str) -> str:
        """Return the collection name for a given source label.

        Raises KeyError if the source is unknown — that's a programmer
        error and we want it to fail loud at startup, not silently
        write to the wrong collection.
        """
        mapping = {
            "openelectricity": self.coll_openelectricity,
            "aemo_nem": self.coll_aemo_nem,
            "aemo_wem": self.coll_aemo_wem,
            "bom": self.coll_bom,
            "aemo_holidays": self.coll_aemo_holidays,
        }
        try:
            return mapping[source]
        except KeyError as e:
            raise KeyError(
                f"Unknown source {source!r}. Known sources: {sorted(mapping)}"
            ) from e

    def unique_key_for_source(self, source: str) -> tuple[str, ...]:
        """Return the unique-key tuple for a given source.

        Same source → same tuple every time (used by bulk_upsert to
        dedupe on retry).
        """
        mapping = {
            "openelectricity": ("network_code", "ts"),
            "aemo_nem": ("region", "ts"),
            "aemo_wem": ("ts",),
            "bom": ("station_id", "ts"),
            "aemo_holidays": ("region", "date"),
        }
        try:
            return mapping[source]
        except KeyError as e:
            raise KeyError(
                f"Unknown source {source!r}. Known sources: {sorted(mapping)}"
            ) from e


@lru_cache(maxsize=1)
def get_mongo_settings() -> MongoSettings:
    """Cached MongoDB settings singleton.

    Same pattern as `get_settings()` — first call instantiates, subsequent
    calls are O(1). The cache is invalidated on process restart (no need
    for explicit invalidation).
    """
    return MongoSettings()


# Re-export for `from ecolens.ingestion.storage.settings import MongoSettings, get_mongo_settings`
__all__ = ["MongoSettings", "get_mongo_settings"]
