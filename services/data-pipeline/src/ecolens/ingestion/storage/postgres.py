"""MongoDB -> PostgreSQL `raw.*` syncer.

See INGESTION.md's "MongoDB -> PostgreSQL Syncer" section for the design
this implements. Every source's MongoDB documents already carry the
target's flat column set verbatim (each fetcher stamps
`ingest_run_id`/`fetched_at`/`source` onto its own already-flat
OUTPUT_COLUMNS before upserting -- see `ecolens.ingestion.storage.mongo`)
so "sync" here is a column projection + upsert, not a real reshape.

The `raw.*` table/column contract (including each source's unique key)
must stay in lockstep with:
  - `ecolens.ingestion.storage.settings.MongoSettings` (collection names,
    `unique_key_for_source`) -- the Mongo side.
  - `warehouse/dbt_project/macros/create_raw_schema.sql` -- the Postgres
    DDL dbt bootstraps `raw.*` from.

Connects to the same Postgres database the dbt project and warehouse
runner already target (`WarehouseRunnerSettings`) rather than inventing a
third near-duplicate pg_* settings surface. Takes that settings object
structurally (`_PgConnParams`, below) instead of importing the class
directly: `ecolens.warehouse` imports from `ecolens.ingestion`, not the
other way around, and a module-level import of
`ecolens.warehouse.runner.settings` would pull in `warehouse.runner`'s
`__init__.py` -- which imports the orchestrator that imports *this*
module -- a real circular import, not a style preference.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

import asyncpg

from ecolens.ingestion.circuit_breaker import retry_with_backoff
from ecolens.ingestion.storage.mongo import get_db
from ecolens.ingestion.storage.settings import MongoSettings, get_mongo_settings
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)


class _PgConnParams(Protocol):
    """Structural stand-in for `WarehouseRunnerSettings` -- see the
    module docstring for why this isn't a direct import."""

    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str
    pg_dsn: str | None


# Column contract per raw.* table -- must match create_raw_schema() in
# warehouse/dbt_project/macros/create_raw_schema.sql exactly.
_ENERGY_COLUMNS: tuple[str, ...] = (
    "ts",
    "network_code",
    "region",
    "data_quality_status",
    "schema_version",
    "demand_mw",
    "price_mwh",
    "market_value",
    "coal_black_mw",
    "coal_brown_mw",
    "gas_ccgt_mw",
    "gas_ocgt_mw",
    "gas_other_mw",
    "hydro_mw",
    "pumped_hydro_mw",
    "wind_mw",
    "solar_utility_mw",
    "solar_rooftop_mw",
    "biomass_mw",
    "distillate_mw",
    "battery_discharge_mw",
    "battery_charge_mw",
    "curtailment_solar_utility_mw",
    "curtailment_wind_mw",
    "total_generation_mw",
    "renewable_proportion",
    "emissions_intensity_kgco2e_per_mwh",
    "interconnector_imports_mw",
    "interconnector_exports_mw",
    "net_import_mw",
    "source",
    "ingest_run_id",
    "fetched_at",
)
_BOM_COLUMNS: tuple[str, ...] = (
    "ts",
    "region",
    "station_id",
    "station_name",
    "schema_version",
    "temp_c",
    "apparent_temp_c",
    "dew_point_c",
    "humidity_pct",
    "wind_speed_kmh",
    "wind_direction_deg",
    "wind_gust_kmh",
    "pressure_hpa",
    "rain_since_9am_mm",
    "rain_last_hour_mm",
    "cloud_oktas",
    "cloud_cover_pct",
    "data_quality_status",
    "source",
    "ingest_run_id",
    "fetched_at",
)
_HOLIDAY_COLUMNS: tuple[str, ...] = (
    "date",
    "region",
    "state",
    "holiday_name",
    "holiday_type",
    "schema_version",
    "is_business_day",
    "is_observed",
    "observed_date",
    "days_until",
    "source",
    "ingest_run_id",
    "fetched_at",
)

# source key -> column contract for its raw.* table (source keys match
# MongoSettings.collection_for_source / unique_key_for_source exactly).
_SOURCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "aemo_nem": _ENERGY_COLUMNS,
    "aemo_wem": _ENERGY_COLUMNS,
    "openelectricity": _ENERGY_COLUMNS,
    "bom": _BOM_COLUMNS,
    "aemo_holidays": _HOLIDAY_COLUMNS,
}


# Not every source's fetcher stores these as native BSON dates (e.g.
# OpenElectricity's `ts` lands as an ISO string) -- coerce defensively
# rather than assume, same as freshness.py already does for its own
# timestamp field.
_TIMESTAMP_COLUMNS = frozenset({"ts", "fetched_at"})
_DATE_COLUMNS = frozenset({"date", "observed_date"})
# BoM's local CSV cache round-trip used to infer the all-numeric-looking
# "1.0" as float64 (fixed at the source in bom/cache.py), so some
# already-ingested Mongo docs still have schema_version stored as a
# float -- coerce here too rather than assume every doc was written
# after that fix.
_STRING_COLUMNS = frozenset({"schema_version"})


def _coerce(column: str, value: Any) -> Any:
    if value is None:
        return None
    # Historical rows written before validators/common.py's clean_nan()
    # fix can still have a bare float('nan') in an optional non-numeric
    # column (e.g. observed_date) -- asyncpg has no float8-vs-date
    # ambiguity to fall back on, so this must be checked before the
    # column-specific casts below. Converting to NULL (rather than
    # leaving NaN) is also correct for genuinely numeric columns: NaN
    # poisons SQL aggregates (avg() over a NaN is NaN) in a way NULL
    # doesn't.
    if isinstance(value, float) and math.isnan(value):
        return None
    if column in _TIMESTAMP_COLUMNS and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if column in _DATE_COLUMNS and isinstance(value, str):
        return date.fromisoformat(value)
    if column in _STRING_COLUMNS and not isinstance(value, str):
        return str(value)
    return value


def _upsert_sql(
    table: str, columns: tuple[str, ...], unique_key: tuple[str, ...]
) -> str:
    placeholders = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
    update_cols = [c for c in columns if c not in unique_key]
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
    # table/columns/unique_key come only from _SOURCE_COLUMNS and
    # MongoSettings.collection_for_source()/unique_key_for_source() --
    # hardcoded internal mappings, never request input.
    return (
        f"insert into {table} ({', '.join(columns)}) values ({placeholders}) "  # nosec B608
        f"on conflict ({', '.join(unique_key)}) do update set {update_clause}"
    )


class RawSyncer:
    """Copies MongoDB raw collections into PostgreSQL `raw.*` tables.

    Idempotent: every insert is an upsert on the same unique key the
    Mongo collection itself is keyed on, so re-running (or overlapping
    incremental windows) never creates duplicates.
    """

    def __init__(
        self,
        mongo_settings: MongoSettings | None = None,
        pg_settings: _PgConnParams | None = None,
    ) -> None:
        self.mongo_settings = mongo_settings or get_mongo_settings()
        if pg_settings is None:
            # Local import: only needed for this fallback (callers normally
            # pass their own settings, e.g. WarehouseRunner passes its own
            # WarehouseRunnerSettings) -- see the module docstring for why
            # this can't be a module-level import.
            from ecolens.warehouse.runner.settings import get_warehouse_runner_settings

            pg_settings = get_warehouse_runner_settings()
        self.pg_settings = pg_settings
        self._pg_pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self.pg_settings.pg_dsn:
            self._pg_pool = await asyncpg.create_pool(
                dsn=self.pg_settings.pg_dsn, min_size=1, max_size=4
            )
        else:
            self._pg_pool = await asyncpg.create_pool(
                host=self.pg_settings.pg_host,
                port=self.pg_settings.pg_port,
                database=self.pg_settings.pg_database,
                user=self.pg_settings.pg_user,
                password=self.pg_settings.pg_password,
                min_size=1,
                max_size=4,
            )

    async def close(self) -> None:
        if self._pg_pool is not None:
            await self._pg_pool.close()
            self._pg_pool = None

    async def sync_one(self, source: str, *, since: datetime | None = None) -> int:
        """Sync one source's Mongo collection into its raw.* table.

        `since` filters on `fetched_at` (incremental catch-up); omit
        for a full resync of the whole collection.
        """
        if self._pg_pool is None:
            raise RuntimeError("RawSyncer.connect() must be called before sync_one()")

        collection_name = self.mongo_settings.collection_for_source(source)
        unique_key = self.mongo_settings.unique_key_for_source(source)
        columns = _SOURCE_COLUMNS[source]
        table = f"raw.{collection_name}"
        chunk_size = self.mongo_settings.mongo_bulk_chunk_size

        query: dict[str, Any] = {}
        if since is not None:
            query["fetched_at"] = {"$gte": since}

        sql = _upsert_sql(table, columns, unique_key)
        collection = get_db()[collection_name]

        synced = 0
        batch: list[tuple[Any, ...]] = []
        async for doc in collection.find(query):
            batch.append(tuple(_coerce(col, doc.get(col)) for col in columns))
            if len(batch) >= chunk_size:
                await self._write_batch(sql, batch)
                synced += len(batch)
                batch = []
        if batch:
            await self._write_batch(sql, batch)
            synced += len(batch)

        log.info("raw_sync.source_synced", source=source, table=table, rows=synced)
        return synced

    async def sync_all(self, *, since: datetime | None = None) -> dict[str, int]:
        """Sync every known source. Returns rows synced per source."""
        return {
            source: await self.sync_one(source, since=since)
            for source in _SOURCE_COLUMNS
        }

    async def _write_batch(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        if self._pg_pool is None:
            raise RuntimeError("RawSyncer.connect() must be called before sync_one()")
        pool = self._pg_pool

        async def _do_write() -> None:
            async with pool.acquire() as conn:
                await conn.executemany(sql, rows)

        # Pooled/serverless Postgres (e.g. Neon's connection pooler) can
        # cancel a long-running or lock-contended batch outright rather
        # than queue it -- asyncpg surfaces that as a plain "operation
        # cancelled" error. Retrying the batch (not the whole sync) is
        # cheap since every row is an idempotent upsert.
        await retry_with_backoff(
            _do_write,
            max_retries=self.mongo_settings.ingest_max_retries,
            backoff_base=self.mongo_settings.ingest_retry_backoff_base,
            on_retry=lambda attempt, exc, delay: log.warning(
                "raw_sync.batch_retry",
                attempt=attempt,
                error=str(exc),
                sleep=delay,
                rows=len(rows),
            ),
        )


def default_lookback(days: int) -> datetime:
    """`since` cutoff for an incremental sync: now - `days`."""
    return datetime.now(timezone.utc) - timedelta(days=days)


__all__ = ["RawSyncer", "default_lookback"]
