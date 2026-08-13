"""Permanent `raw_marts.*` archive on the second database (root TODO.md's
"save raw and raw.marts in seperate database uing seperate Database_URL
(so taht i can save 2*512 mb data)").

`app/retention/pruning.py`'s own module docstring names this gap
explicitly: "Curated (dbt marts) retention is a documented follow-up,
not implemented here... the marts schema's own retention needs (which
tables, what natural key) weren't researched as part of this change and
deserve their own pass rather than a rushed guess." This is that pass.

Why not a live cross-database join (the postgres_fdw approach tried and
shelved earlier)? Measured real cost: 1.7-3s of added per-query latency
from FDW's network round-trip, on two load-bearing paths --
`/v1/forecast`'s live serving (`ml/data.py`'s `load_latest_window`) and
dbt's own `int_demand_with_weather.sql`, which runs many small
correlated LATERAL lookups per row (the exact query shape that already
caused a 51-minute TimescaleDB chunk-scan blowup once this same
session). Both risks disappear with a periodic, offline copy instead:
dbt keeps building `raw_marts.*` entirely against the primary database
(fast, local, zero change to the dbt project or its risk profile);
this module *afterward* copies rows older than `Settings.
marts_local_retention_days` to the second database via two ordinary
same-process connections (no cross-database SQL at all -- extract from
one connection, load via `COPY` on the other, same "export before
prune" safe ordering `retention/cold_storage.py` already established
for R2), then deletes them from the primary. Live app code never
changes: every existing `raw_marts.*` reader keeps querying the primary
database's rolling window exactly as it does today.

`raw_marts.*`'s dbt-materialized tables have no PRIMARY KEY at all
(confirmed live) -- the second database's own copies (`0008_marts_
archive_schema_db2.sql`) DO get one, on each mart's real natural key, so
`ON CONFLICT DO NOTHING` makes a retry after a crash between the copy
and the delete step safe (the narrow risk window this design accepts,
same class of risk `cold_storage.py`'s R2-export-then-prune already
carries).

**Batched by `_BATCH_DAYS`-wide time windows, one fresh connection pair
per batch** -- the first real run (2026-08-09) held one connection pair
open across a single giant `WHERE ts < cutoff` sweep (423,722 rows for
`fct_emissions_5min` alone, a full year of accumulated history since
this is the first run ever) and hit "connection is closed" ~5.5 minutes
in, on all 3 of the larger fact tables -- Neon's pooler drops a
connection that's checked out that long. No data was lost (archive-then-
prune order meant nothing had been deleted from the primary yet), but it
confirmed a single-shot transfer doesn't scale to a real first-run
backlog. Each batch here is small enough to finish in seconds, and nothing
holds a connection across more than one batch.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import marts_archive_rows_total
from app.db.session import get_marts_archive_session, get_session

log = get_logger(__name__)

# table -> its own time column. Only the 4 time-series marts get a
# rolling window + archive -- the 2 `dim_*` marts are small reference
# tables (14/6 rows, measured live) with no time dimension to window on;
# `_mirror_dim_table` below just fully mirrors those every run instead.
_MARTS_TIME_TABLES: dict[str, str] = {
    "fct_emissions_5min": "ts",
    "fct_energy_demand": "ts",
    "fct_carbon_intensity": "hour",
    "fct_generation_mix": "hour",
}

_MARTS_DIM_TABLES: tuple[str, ...] = ("dim_facility", "dim_energy_mix")

# A week-wide half-open [start, end) range on both the SELECT and the
# matching DELETE keeps every batch a safe, complete unit -- no risk of
# archiving part of a timestamp's row-group (multiple regions/fuel_types
# share one `ts`/`hour` value) while deleting a different part of it.
# ~1,100-8,000 rows/week at this project's real measured volumes --
# small enough to finish well inside any pooler's idle-connection window.
_BATCH_DAYS = 7


async def _min_time(session: AsyncSession, table: str, column: str) -> datetime | None:
    result = await session.execute(
        text(f'SELECT min("{column}") FROM raw_marts."{table}"')  # nosec B608 -- `table`/`column` come from this module's own fixed `_MARTS_TIME_TABLES` dict, never user input
    )
    return result.scalar()


async def _fetch_range(
    session: AsyncSession, table: str, column: str, start: datetime, end: datetime
) -> pd.DataFrame:
    result = await session.execute(
        text(
            f'SELECT * FROM raw_marts."{table}" '  # nosec B608 -- `table`/`column` come from this module's own fixed `_MARTS_TIME_TABLES` dict, never user input
            f'WHERE "{column}" >= :start AND "{column}" < :end'
        ),
        {"start": start, "end": end},
    )
    rows = result.mappings().all()
    return pd.DataFrame(rows)


async def _fetch_all(session: AsyncSession, table: str) -> pd.DataFrame:
    result = await session.execute(
        text(f'SELECT * FROM raw_marts."{table}"')  # nosec B608 -- `table` comes only from this module's own fixed `_MARTS_DIM_TABLES` tuple, never user input
    )
    rows = result.mappings().all()
    return pd.DataFrame(rows)


async def _copy_into_archive(archive_session: AsyncSession, df: pd.DataFrame, table: str) -> int:
    """`COPY`-into-temp-table + `INSERT ... ON CONFLICT DO NOTHING` into
    the second database's `raw_marts.{table}` -- same mechanism `app/
    loaders/postgres_loader.py` already uses for `raw.*`, just pointed at
    the archive connection instead of the primary one."""
    if df.empty:
        return 0

    raw_connection = await archive_session.connection()
    driver_connection = (await raw_connection.get_raw_connection()).driver_connection
    if driver_connection is None:
        raise RuntimeError("no underlying asyncpg connection")

    columns = list(df.columns)
    csv_text = df.to_csv(index=False, header=False, na_rep=r"\N")
    buffer = io.BytesIO(csv_text.encode("utf-8"))

    staging_table = f"_archive_{uuid.uuid4().hex[:12]}"
    quoted_columns = ", ".join(f'"{c}"' for c in columns)

    # `table` always comes from this module's own fixed table lists
    # above, never user input -- nosec B608 applies to all three
    # statements below, same reasoning as postgres_loader.py's identical
    # pattern.
    async with driver_connection.transaction():
        await driver_connection.execute(
            f'CREATE TEMP TABLE "{staging_table}" '  # nosec B608
            f'(LIKE raw_marts."{table}" INCLUDING DEFAULTS) ON COMMIT DROP'
        )
        await driver_connection.copy_to_table(
            staging_table,
            source=buffer,
            columns=columns,
            format="csv",
            null=r"\N",
        )
        result = await driver_connection.execute(
            f'INSERT INTO raw_marts."{table}" ({quoted_columns}) '  # nosec B608
            f'SELECT {quoted_columns} FROM "{staging_table}" '
            "ON CONFLICT DO NOTHING"
        )
    return int(result.split()[-1])


async def _prune_range(
    session: AsyncSession, table: str, column: str, start: datetime, end: datetime
) -> int:
    result = await session.execute(
        text(
            f'DELETE FROM raw_marts."{table}" '  # nosec B608 -- `table`/`column` come from this module's own fixed `_MARTS_TIME_TABLES` dict, never user input
            f'WHERE "{column}" >= :start AND "{column}" < :end'
        ),
        {"start": start, "end": end},
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def _archive_and_prune_table(
    table: str, column: str, cutoff: datetime
) -> dict[str, int] | None:
    """One table's full backlog, `_BATCH_DAYS` at a time -- each batch
    opens its own fresh primary+archive session pair (never held across
    more than one batch) and commits independently, so a failure partway
    through a large first-run backlog only loses that one batch's
    progress, not the whole table's."""
    async with get_session() as primary:
        floor = await _min_time(primary, table, column)
    if floor is None or floor >= cutoff:
        return None

    archived_total = 0
    pruned_total = 0
    batch_start = floor
    while batch_start < cutoff:
        batch_end = min(batch_start + timedelta(days=_BATCH_DAYS), cutoff)
        async with get_session() as primary, get_marts_archive_session() as archive:
            df = await _fetch_range(primary, table, column, batch_start, batch_end)
            if not df.empty:
                archived = await _copy_into_archive(archive, df, table)
                marts_archive_rows_total.labels(table=table).inc(archived)
                rows_pruned = await _prune_range(primary, table, column, batch_start, batch_end)
                archived_total += archived
                pruned_total += rows_pruned
        batch_start = batch_end

    if archived_total == 0 and pruned_total == 0:
        return None
    return {"archived": archived_total, "pruned": pruned_total}


async def archive_and_prune_marts(
    days: int | None = None,
) -> tuple[dict[str, dict[str, int]], datetime]:
    """Archives `raw_marts.*` rows older than `days` (`Settings.
    marts_local_retention_days` if omitted) to the second database, then
    deletes them from the primary once the archive copy has actually
    succeeded -- `_BATCH_DAYS` at a time (`_archive_and_prune_table`),
    not one giant sweep. Also mirrors the 2 small dim tables in full
    every run (upsert, never deleted from the primary -- they're tiny
    reference data, not history).

    No-ops (returns `({}, cutoff)`) if `RAW_MARTS_DATABASE_URL` isn't
    configured -- same "optional infra, not a hard failure" convention
    `object_storage_configured` already uses elsewhere in this service.

    Returns `({table: {"archived": n, "pruned": n}}, cutoff)` for
    whatever time-series tables had anything to do; dim-table mirrors
    are logged but not included in the returned dict (they're never
    pruned, so "pruned" would always be 0 and misleading).
    """
    settings = get_settings()
    window = days if days is not None else settings.marts_local_retention_days
    cutoff = datetime.now(UTC) - timedelta(days=window)

    if not settings.raw_marts_archive_configured:
        log.info("marts_archive.skipped_not_configured")
        return {}, cutoff

    async with get_session() as primary, get_marts_archive_session() as archive:
        for table in _MARTS_DIM_TABLES:
            try:
                df = await _fetch_all(primary, table)
                if df.empty:
                    continue
                archived = await _copy_into_archive(archive, df, table)
                marts_archive_rows_total.labels(table=table).inc(archived)
                log.info("marts_archive.dim_mirrored", table=table, rows=len(df))
            except Exception as exc:  # noqa: BLE001 - one table's failure must not stop the rest
                log.error("marts_archive.dim_mirror_failed", table=table, error=str(exc))

    results: dict[str, dict[str, int]] = {}
    for table, column in _MARTS_TIME_TABLES.items():
        try:
            table_result = await _archive_and_prune_table(table, column, cutoff)
            if table_result is not None:
                results[table] = table_result
                log.info("marts_archive.table_completed", table=table, **table_result)
        except Exception as exc:  # noqa: BLE001 - one table's archive/prune failure must not stop the rest
            log.error(
                "marts_archive.table_failed",
                table=table,
                error=str(exc),
                partial_results=results.get(table),
            )

    if results:
        log.info(
            "marts_archive.completed",
            days=window,
            cutoff=cutoff.isoformat(),
            results=results,
        )
    return results, cutoff
