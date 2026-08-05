"""Read-only DuckDB access to the shared staging file `services/
ingestion` writes into (`Settings.duckdb_staging_dir`).

This service **never** opens the file read-write — writing/appending is
entirely `services/ingestion`'s job (`pipeline.duckdb_staging.
stage_dataframe`). DuckDB only allows a single read-write connection to
a file at a time, but any number of concurrent read-only connections —
opening `read_only=True` here is not just a safety convention, it's what
lets this service's consumer and ingestion's own producer share the file
without fighting over a lock.

One real per-source table (`bom_observations`, `aemo_nem_dispatch`, ...)
inside the shared file, rows tagged `_ingest_run_id` so one run's data
stays extractable from a table many runs append into — same shape
ingestion's own `pipeline.duckdb_staging.py` documents; this module is
the consumer-side mirror of that producer-side design, not a
reinterpretation of it.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from app.core.config import get_settings

_RUN_ID_COLUMN = "_ingest_run_id"


def staging_path() -> Path:
    settings = get_settings()
    return Path(settings.duckdb_staging_dir) / "landed.duckdb"


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    result = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone()
    return bool(result and result[0] > 0)


def read_run(table: str, run_id: str) -> pd.DataFrame:
    """Read one run's rows back out of the shared staging file,
    `_ingest_run_id`-filtered, that bookkeeping column excluded from the
    result. Empty (not an error) if the shared file, `table`, or that
    run's rows don't exist — a landed event referencing a run whose rows
    were already consumed (a redelivered message) is a real, expected
    case, not a bug.
    """
    path = staging_path()
    if not path.exists():
        return pd.DataFrame()

    con = duckdb.connect(str(path), read_only=True)
    try:
        if not _table_exists(con, table):
            return pd.DataFrame()
        return con.execute(
            f"SELECT * EXCLUDE ({_RUN_ID_COLUMN}) FROM {table} WHERE {_RUN_ID_COLUMN} = ?",  # nosec B608 -- `table` always comes from the RabbitMQ payload's own `table` field, sourced from ingestion's registry.SOURCES, never user input
            [run_id],
        ).df()
    finally:
        con.close()
