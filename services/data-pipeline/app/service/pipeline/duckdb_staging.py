"""DuckDB raw-landing staging (`overview.md` §1 Storage).

Each ingest run stages its fetched DataFrame in its own `.duckdb` file
under `Settings.duckdb_staging_dir`. `pipeline.tasks._common.standard_run`
calls `stage_dataframe` right after a successful fetch; `pipeline.
warehouse_sync`'s RabbitMQ consumer calls `read_staged` then
`delete_staged` once the data is safely in Postgres `raw.*`.

One file per run, not one shared file, because DuckDB only supports a
single read-write connection to a given file at a time — see
`Settings.duckdb_staging_dir`'s docstring in `config.py` for why that
would be a real problem with one shared file (the short-lived ingest
process and the long-running warehouse-sync consumer fighting over the
same lock) and isn't with per-run files.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from app.core.config import get_settings

_TABLE = "landed"


def _staging_path(table: str, run_id: str) -> Path:
    settings = get_settings()
    return Path(settings.duckdb_staging_dir) / f"{table}-{run_id}.duckdb"


def stage_dataframe(df: pd.DataFrame, table: str, run_id: str) -> tuple[str, int]:
    """Write `df` into a new per-run DuckDB file. Returns `(path, rows)`.

    A no-op for an empty DataFrame — no file is created, `("", 0)` is
    returned — matching the old `land_and_load`'s empty-fetch behaviour
    (nothing worth landing or syncing).

    The file holds one run's data in a single table (`landed`); `table`
    only names the file for easy debugging (`ls` shows which Postgres
    `raw.*` table each staged file is bound for) — the RabbitMQ event
    `_common.py` publishes alongside this carries the actual routing
    info the consumer needs, so `read_staged`/`delete_staged` below just
    take the literal path back.
    """
    if df.empty:
        return "", 0

    path = _staging_path(table, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(path))
    try:
        con.register("df_view", df)
        con.execute(f"CREATE TABLE {_TABLE} AS SELECT * FROM df_view")  # nosec B608 -- `_TABLE` is a fixed module-level constant, not user input
    finally:
        con.close()

    return str(path), len(df)


def read_staged(path: str) -> pd.DataFrame:
    """Read a staged run's DataFrame back out of its DuckDB file."""
    con = duckdb.connect(path, read_only=True)
    try:
        return con.execute(f"SELECT * FROM {_TABLE}").df()  # nosec B608 -- `_TABLE` is a fixed module-level constant, not user input
    finally:
        con.close()


def delete_staged(path: str) -> None:
    """Remove a staged run's DuckDB file after it's safely in Postgres.

    Safe to call on an already-missing file (idempotent — a retried
    consumer run shouldn't blow up on cleanup that already happened).
    """
    Path(path).unlink(missing_ok=True)
