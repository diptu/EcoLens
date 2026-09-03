"""Ingestion-layer settings: per-source table names + network/retry tunables.

File path:
    services/data-pipeline/src/ecolens/ingestion/core/settings.py

Why a separate file?
    * Keeps per-source table-name mapping and retry/concurrency tunables
      together, independent of the global `ecolens.config.Settings` (which
      holds every other service's config).
    * Lets the ingestion layer override defaults without touching that
      global settings object.

Formerly `MongoSettings`: this class used to also own MongoDB connection
config (URI, pool sizes, timeouts, retry policy, write concern) back when
MongoDB was the raw landing zone. Now that DuckDB is the sole raw store
(see `ecolens.ingestion.db.duckdb_store`), those connection-specific
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
from pathlib import Path

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

    # Where `PATCH /v1/data-sources/{id}` persists per-source
    # enabled/cron admin overrides (ingestion/core/data_source_overrides.py)
    # -- relative to CWD by default, same convention as
    # `Settings.historical_duckdb_path`.
    data_source_overrides_path: Path = Path("data/data_source_overrides.json")

    # Append-only JSONL run history (ingestion/core/run_history.py),
    # one line per `scripts/trigger_ingest_*.py` completion -- same
    # convention/location family as `WarehouseRunnerSettings.log_dir`'s
    # `warehouse-runs.jsonl`, just ingestion's own file since ingestion
    # can't depend on warehouse settings (see the layering note on
    # `data_source_health_threshold_minutes_*` above).
    ingestion_runs_log_path: Path = Path("data/log/ingestion-runs.jsonl")

    # ── Anomaly detection (root TODO.md's "Anomaly Detection" section) ──
    # Rule thresholds live here, not hardcoded in
    # `ingestion/service/anomaly/rules.py`, same reasoning as every
    # `ingest_*` tunable above -- overridable per-environment without a
    # code change (e.g. `ANOMALY_PRICE_CAP_NEM`).
    #
    # AEMO's regulated Market Price Cap/Floor for the NEM (2024-25
    # figures) -- reused as-is for WEM too: WEM's own market mechanism
    # differs, but this is meant to catch "wildly implausible," not
    # replicate WEM's actual price-setting rules exactly.
    anomaly_price_cap: float = 17_500.0
    anomaly_price_floor: float = -1_000.0
    # A same-region demand jump this large between consecutive intervals
    # within one ingest batch is far outside normal dispatch variation
    # (a real event, e.g. a major contingency, can genuinely cause this --
    # it's flagged, never dropped, see scorer.py).
    anomaly_demand_jump_fraction: float = 0.5
    anomaly_bom_temp_min_c: float = -10.0
    anomaly_bom_temp_max_c: float = 55.0
    anomaly_bom_humidity_min_pct: float = 0.0
    anomaly_bom_humidity_max_pct: float = 100.0
    anomaly_bom_wind_speed_max_kmh: float = 300.0
    # Staleness = fetched_at - ts. Source-specific because publish lag
    # genuinely differs: AEMO NEM's own ~4am-next-day file publish quirk
    # (see aemo_nem/engine.py's module docstring) means a perfectly
    # normal NEM row can be 24h+ stale by this measure, while WEM/
    # OpenElectricity/BoM are all much closer to real-time.
    anomaly_staleness_minutes_aemo_nem: float = 2_000.0
    anomaly_staleness_minutes_aemo_wem: float = 180.0
    anomaly_staleness_minutes_openelectricity: float = 180.0
    anomaly_staleness_minutes_bom: float = 120.0
    # Rolling median+MAD baseline (ingestion/service/anomaly/baseline.py).
    anomaly_baseline_lookback_days: int = 7
    # Below this many history points for a given (source, entity, metric),
    # the baseline is too thin to trust -- skip statistical scoring
    # entirely rather than score against a handful of points (a genuine
    # cold-start case: a newly onboarded region/station, or the first
    # week after a fresh deploy).
    anomaly_baseline_min_samples: int = 20
    # The standard "modified z-score" outlier threshold for a MAD-based
    # baseline (Iglewicz & Hoaglin) -- not the more familiar 3-sigma rule
    # of thumb, which assumes a plain std-dev baseline this deliberately
    # isn't using (see baseline.py's own docstring for why MAD, not std).
    anomaly_robust_zscore_threshold: float = 3.5

    # ── v2: periodically-retrained IsolationForest
    # (ingestion/service/anomaly/isolation_forest.py) ────────────────────
    # A kill switch: false skips loading/scoring against persisted models
    # entirely (e.g. before any have ever been trained, or to roll back
    # to v1-only scoring without a code change).
    anomaly_isolation_forest_enabled: bool = True
    # Deliberately longer than anomaly_baseline_lookback_days (7) -- v1's
    # per-batch baseline is rebuilt fresh every call so it stays cheap at
    # any window size, but this model is only *retrained* daily (see
    # scripts/train_anomaly_isolation_forest.py), so it can afford a
    # wider window for a more stable notion of "normal" without costing
    # anything on the hot ingest path.
    anomaly_isolation_forest_lookback_days: int = 14
    # Below this many (entity, timestamp) samples for a given
    # (source, metric), training is skipped for it this run -- same
    # cold-start reasoning as anomaly_baseline_min_samples, just a
    # higher bar since IsolationForest needs more data than a median+MAD
    # calculation to learn a meaningful "normal" region.
    anomaly_isolation_forest_min_samples: int = 200
    anomaly_isolation_forest_n_estimators: int = 100
    # sklearn's own default ('auto') picks a threshold internally in a
    # way that varies with dataset size in ways that are hard to reason
    # about across 9 independently-trained (source, metric) models --
    # an explicit fraction keeps every model's severity scale comparable.
    anomaly_isolation_forest_contamination: float = 0.01
    # No fixed severity-scale setting here (an earlier draft of this had
    # one) -- `decision_function()`'s real range varies per model with
    # dataset size/dimensionality (isolation depth has a floor, so a
    # sufficiently extreme point isolates in ~1 split and further
    # extremity doesn't push the score any more negative), confirmed
    # empirically while building this. Each model instead calibrates
    # against its *own* training-data severity floor -- see
    # `isolation_forest.py`'s `LoadedIsolationForest.severity_floor`.

    # ── Data-source health (root TODO.md's `GET /v1/data-sources`) ──────
    # Deliberately mirrors `WarehouseRunnerSettings.freshness_threshold_*`
    # (same real values) rather than importing it -- ingestion is the
    # lower layer (warehouse depends on it, never the reverse), so
    # importing a warehouse setting here would invert that. Not the same
    # thing as `anomaly_staleness_minutes_*` above, which is a much
    # looser per-*record* rule (a single row's fetched_at-vs-ts gap);
    # this is "how long since the last successful fetch at all" -- the
    # same question `SourceFreshnessChecker` (warehouse layer) already
    # answers, at the same thresholds, for a different consumer.
    data_source_health_threshold_minutes_aemo: float = 1_800.0  # 30h
    data_source_health_threshold_minutes_bom: float = 120.0  # 2h
    data_source_health_threshold_minutes_holidays: float = 10_080.0  # 7d

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

    def timestamp_column_for_source(self, source: str) -> str:
        """The column `ingestion/service/anomaly/rules.py`'s staleness
        check and `baseline.py`'s rolling baseline both treat as "when
        this record is about" -- `ts` for every source except holidays,
        which is calendar-dated (`date`), not timestamped.
        """
        return "date" if source == "aemo_holidays" else "ts"

    def entity_columns_for_source(self, source: str) -> tuple[str, ...]:
        """`unique_key_for_source(source)` minus the timestamp/date
        column -- what `baseline.py` groups its rolling median+MAD
        baseline by (e.g. `region` for NEM, `station_id` for BoM).
        WEM has no entity dimension (a single zone, keyed on `ts`
        alone) -- an empty tuple means "one global series," not
        "unknown source" (unlike the KeyError `unique_key_for_source`
        itself raises for a genuinely unknown source).
        """
        ts_col = self.timestamp_column_for_source(source)
        return tuple(c for c in self.unique_key_for_source(source) if c != ts_col)

    def metric_columns_for_source(self, source: str) -> tuple[str, ...]:
        """Numeric columns worth rule-checking/baselining for `source`.
        Deliberately a curated subset, not "every numeric column" --
        v1 scope is the metrics root TODO.md's Anomaly Detection section
        calls out by name (demand/price for the energy sources,
        temp/humidity/wind for BoM); the 16-fuel generation-mix columns
        are a reasonable v2 extension, not required for a working v1.
        Holidays has no numeric metrics worth baselining -- an empty
        tuple, same "valid answer, not unknown source" reasoning as
        `entity_columns_for_source`'s WEM case.
        """
        mapping: dict[str, tuple[str, ...]] = {
            "openelectricity": ("demand_mw", "price_mwh"),
            "aemo_nem": ("demand_mw", "price_mwh"),
            "aemo_wem": ("demand_mw", "price_mwh"),
            "bom": ("temp_c", "humidity_pct", "wind_speed_kmh"),
            "aemo_holidays": (),
        }
        try:
            return mapping[source]
        except KeyError as e:
            raise KeyError(
                f"Unknown source {source!r}. Known sources: {sorted(mapping)}"
            ) from e

    def staleness_threshold_minutes_for_source(self, source: str) -> float | None:
        """Max plausible `fetched_at - ts` for `source`, or `None` for a
        source staleness doesn't apply to (holidays: `date` is often
        legitimately far in the future/past of `fetched_at` by design,
        not a sign of a stale fetch).
        """
        mapping: dict[str, float] = {
            "openelectricity": self.anomaly_staleness_minutes_openelectricity,
            "aemo_nem": self.anomaly_staleness_minutes_aemo_nem,
            "aemo_wem": self.anomaly_staleness_minutes_aemo_wem,
            "bom": self.anomaly_staleness_minutes_bom,
        }
        return mapping.get(source)


@lru_cache(maxsize=1)
def get_ingestion_settings() -> IngestionSettings:
    """Cached settings singleton.

    Same pattern as `get_settings()` — first call instantiates, subsequent
    calls are O(1). The cache is invalidated on process restart (no need
    for explicit invalidation).
    """
    return IngestionSettings()


__all__ = ["IngestionSettings", "get_ingestion_settings"]
