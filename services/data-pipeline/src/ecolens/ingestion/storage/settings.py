"""Ingestion-layer settings: per-source table names + network/retry tunables.

File path:
    services/data-pipeline/src/ecolens/ingestion/storage/settings.py

Why a separate file?
    * Keeps per-source table-name mapping and retry/concurrency tunables
      together, independent of the global `ecolens.config.Settings` (which
      holds every other service's config).
    * Lets the ingestion layer override defaults without touching that
      global settings object.

Formerly `MongoSettings`: this class used to also own MongoDB connection
config (URI, pool sizes, timeouts, retry policy, write concern) back when
MongoDB was the raw landing zone. Now that DuckDB is the sole raw store
(see `ecolens.ingestion.storage.duckdb_store`), those connection-specific
fields are gone -- `table_for_source()`/`unique_key_for_source()` map a
source name to its DuckDB table name and upsert key, and the `ingest_*`
fields are generic HTTP-fetch tunables (concurrency, retry/backoff,
circuit-breaker) that were never actually Mongo-specific to begin with,
just co-located here historically.

`duckdb_store.py` reads from these settings. End-users can override any
field via environment variables (e.g. `INGEST_MAX_RETRIES`).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    """Per-source table-name mapping + ingestion network tunables.

    Independent of the global `Settings` class so the ingestion layer can
    be tuned (e.g. higher concurrency for a busy pipeline) without
    affecting the rest of the service.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── DuckDB table names (centralised, easy to override) ──────────────
    table_openelectricity: str = "openelectricity_responses"
    table_aemo_nem: str = "aemo_nem_dispatch"
    table_aemo_wem: str = "aemo_wem_dispatch"
    table_bom: str = "bom_observations"
    table_aemo_holidays: str = "aemo_holidays"

    # ── Ingest tunables ───────────────────────────────────────────────────
    ingest_concurrent_sources: int = 4
    ingest_concurrent_requests_per_source: int = 6
    ingest_max_retries: int = 3
    ingest_retry_backoff_base: float = 1.5
    ingest_circuit_breaker_threshold: int = 3
    ingest_circuit_breaker_timeout_seconds: int = 300

    # ── Helpers ────────────────────────────────────────────────────────
    def table_for_source(self, source: str) -> str:
        """Return the DuckDB table name for a given source label.

        Raises KeyError if the source is unknown — that's a programmer
        error and we want it to fail loud at startup, not silently
        write to the wrong table.
        """
        mapping = {
            "openelectricity": self.table_openelectricity,
            "aemo_nem": self.table_aemo_nem,
            "aemo_wem": self.table_aemo_wem,
            "bom": self.table_bom,
            "aemo_holidays": self.table_aemo_holidays,
        }
        try:
            return mapping[source]
        except KeyError as e:
            raise KeyError(
                f"Unknown source {source!r}. Known sources: {sorted(mapping)}"
            ) from e

    def unique_key_for_source(self, source: str) -> tuple[str, ...]:
        """Return the unique-key tuple for a given source.

        Same source → same tuple every time (used by
        `duckdb_store.write_historical` to dedupe on retry -- an upsert
        with a key already present overwrites in place).
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
def get_ingestion_settings() -> IngestionSettings:
    """Cached settings singleton.

    Same pattern as `get_settings()` — first call instantiates, subsequent
    calls are O(1). The cache is invalidated on process restart (no need
    for explicit invalidation).
    """
    return IngestionSettings()


__all__ = ["IngestionSettings", "get_ingestion_settings"]
