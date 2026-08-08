"""`VACUUM ANALYZE` after a large prune (README Phase 3 — "reclaim disk
space immediately after large chunks of historical data are purged,
preventing dead tuples from exhausting the 0.5 GB limit").

`VACUUM` cannot run inside a transaction block — a plain `AsyncSession`
(`app.db.session.get_session`) always wraps its work in one, so this
grabs a raw connection with `isolation_level="AUTOCOMMIT"` instead,
scoped to just this one call.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.session import get_engine
from app.retention.marts_archive import _MARTS_TIME_TABLES
from app.retention.pruning import _PRUNABLE_TABLES

log = get_logger(__name__)


async def _vacuum_analyze(schema: str, tables: list[str]) -> list[str]:
    engine = get_engine()
    async with engine.connect() as connection:
        autocommit_connection = await connection.execution_options(
            isolation_level="AUTOCOMMIT"
        )
        for table in tables:
            # `schema`/`table` always come from this module's own fixed
            # table lists, never user input; a bound param isn't valid
            # here regardless -- VACUUM's target is a plain identifier,
            # not an expression Postgres accepts a placeholder for.
            # nosec B608.
            await autocommit_connection.exec_driver_sql(
                f'VACUUM ANALYZE {schema}."{table}"'  # nosec B608
            )
    return tables


async def vacuum_analyze_raw_tables() -> list[str]:
    """Runs `VACUUM ANALYZE` on every table `retention.pruning` prunes
    (same table set, `raw.aemo_holidays` excluded for the same reason).
    Returns the list of tables actually vacuumed.
    """
    tables = await _vacuum_analyze("raw", list(_PRUNABLE_TABLES))
    log.info("retention.vacuum_analyzed", tables=tables)
    return tables


async def vacuum_analyze_marts_tables() -> list[str]:
    """Runs `VACUUM ANALYZE` on the primary database's `raw_marts.*`
    time-series tables (same table set `retention.marts_archive` prunes)
    -- a large first-run/backlog prune leaves dead tuples that still
    count against the free-tier size cap until reclaimed, same reasoning
    `vacuum_analyze_raw_tables` already established for `raw.*`."""
    tables = await _vacuum_analyze("raw_marts", list(_MARTS_TIME_TABLES))
    log.info("marts_archive.vacuum_analyzed", tables=tables)
    return tables
