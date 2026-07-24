"""DuckDB-backed local historical store for the ingestion layer.

Bulk historical backfills (e.g. `HistoricalFetcher`'s 2-3 years of BoM
weather via Open-Meteo/ERA5 -- see `sources/bom/historical.py` and
`scripts/backfill_bom_historical.py`) land in MongoDB the same as
live-fetched docs, which means they're subject to the same
`archive_after_days` cutoff in `warehouse/runner/archive.py`'s Stage 6 --
currently a hard delete with no backup (see TODO.md's ECO-150..157).
Writing the same docs into a local DuckDB file at ingest time gives a
durable, typed, queryable historical record that survives that deletion
and doesn't need a live Mongo/Postgres connection to query later (e.g.
from a notebook, ad hoc, offline).

One table per source, named after `MongoSettings.collection_for_source`
so it lines up with the Mongo collection it mirrors. Upserts on the same
compound key Mongo uses (`MongoSettings.unique_key_for_source`), so
re-running a backfill is idempotent instead of duplicating rows -- the
same contract `ecolens.ingestion.storage.mongo.bulk_upsert` already
gives callers.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ecolens.config import get_settings
from ecolens.ingestion.storage.settings import get_mongo_settings
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)


def _quote(name: str) -> str:
    return f'"{name}"'


def _resolve_path(db_path: Path | None) -> Path:
    return db_path if db_path is not None else get_settings().historical_duckdb_path


def write_historical(
    source: str,
    docs: list[dict[str, Any]],
    *,
    db_path: Path | None = None,
) -> int:
    """Upsert `docs` into the local DuckDB historical store for `source`.

    Idempotent on `MongoSettings.unique_key_for_source(source)` -- a doc
    with a key already present overwrites in place rather than
    duplicating, so re-running the same backfill window twice is safe.
    Returns `len(docs)` (docs attempted), matching `bulk_upsert`'s
    "0 for an empty batch" contract; DuckDB's upsert doesn't cheaply
    distinguish inserted vs. updated rows the way Mongo's `UpdateOne`
    result does.
    """
    if not docs:
        return 0

    path = _resolve_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    mongo_settings = get_mongo_settings()
    table = mongo_settings.collection_for_source(source)
    key_columns = mongo_settings.unique_key_for_source(source)

    df = pd.DataFrame(docs)
    for col in df.columns:
        if df[col].map(lambda v: isinstance(v, datetime)).any():
            df[col] = pd.to_datetime(df[col], utc=True)

    con = duckdb.connect(str(path))
    try:
        _upsert(con, table, df, key_columns)
    finally:
        con.close()

    log.info(
        "historical.duckdb_write",
        source=source,
        table=table,
        path=str(path),
        rows=len(docs),
    )
    return len(docs)


def _upsert(
    con: duckdb.DuckDBPyConnection,
    table: str,
    df: pd.DataFrame,
    key_columns: tuple[str, ...],
) -> None:
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone()
    if not exists:
        con.execute(f"CREATE TABLE {_quote(table)} AS SELECT * FROM df LIMIT 0")
        pk = ", ".join(_quote(c) for c in key_columns)
        con.execute(f"ALTER TABLE {_quote(table)} ADD PRIMARY KEY ({pk})")

    conflict_cols = ", ".join(_quote(c) for c in key_columns)
    update_cols = [c for c in df.columns if c not in key_columns]
    if update_cols:
        set_clause = ", ".join(
            f"{_quote(c)} = EXCLUDED.{_quote(c)}" for c in update_cols
        )
        on_conflict = f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {set_clause}"
    else:
        on_conflict = f"ON CONFLICT ({conflict_cols}) DO NOTHING"
    con.execute(f"INSERT INTO {_quote(table)} SELECT * FROM df {on_conflict}")


def read_historical(
    source: str,
    *,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Read the full historical table for `source`.

    Returns an empty DataFrame if nothing has been written yet for this
    source (no file, or file exists but this source's table doesn't) --
    callers don't need to special-case "never backfilled" vs. "backfilled,
    zero rows."
    """
    path = _resolve_path(db_path)
    if not path.exists():
        return pd.DataFrame()

    table = get_mongo_settings().collection_for_source(source)
    con = duckdb.connect(str(path), read_only=True)
    try:
        exists = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()
        if not exists:
            return pd.DataFrame()
        return con.execute(f"SELECT * FROM {_quote(table)}").fetchdf()
    finally:
        con.close()


__all__ = ["write_historical", "read_historical"]
