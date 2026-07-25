"""DuckDB-backed raw store for the ingestion layer.

This is the sole raw-data landing zone for the ingestion pipeline: every
live fetcher (`sources/*/engine.py`) and every historical backfill
(`HistoricalFetcher`, `scripts/backfill_bom_historical.py`,
`ingestion/api.py`'s `/ingestion/historical`) writes here via
`write_historical()`. `warehouse/runner/postgres.py`'s `RawSyncer` reads
from these tables to populate Postgres `raw.*`, which dbt builds from.

One table per source, named after `IngestionSettings.table_for_source`.
Upserts on each source's compound unique key
(`IngestionSettings.unique_key_for_source`), so re-ingesting the same
window twice is idempotent instead of duplicating rows.

DuckDB allows exactly one read-write connection to a file at a time --
`_connect_with_retry` below retries with backoff instead of failing
immediately on a transient lock conflict (e.g. two fetchers writing at
once, or a short-lived interactive session).
"""

from __future__ import annotations

import random
import time
import uuid
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar

import duckdb
import pandas as pd

from ecolens.config import get_settings
from ecolens.ingestion.storage.settings import get_ingestion_settings
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")

# DuckDB allows exactly one read-write connection to a file at a time --
# a second connection attempt while one is open raises duckdb.IOException
# ("Could not set lock on file") immediately rather than queueing. Since
# DuckDB is now the sole raw store (no MongoDB safety net to fall back
# on), a transient lock conflict between concurrent fetchers -- or a
# short-lived interactive session someone left open -- must be retried,
# not treated as a hard failure on the first attempt.
_LOCK_RETRY_MAX_ATTEMPTS = 5
_LOCK_RETRY_BACKOFF_BASE = 0.5  # seconds; attempt N waits ~0.5*2**(N-1)


def _connect_with_retry(path: Path, *, read_only: bool) -> duckdb.DuckDBPyConnection:
    """`duckdb.connect()`, retrying on a lock conflict with backoff+jitter.

    Only retries `duckdb.IOException` (the lock-conflict error) -- any
    other error (a genuinely corrupt file, a permissions problem) fails
    immediately, since retrying wouldn't help.
    """
    last_exc: duckdb.IOException | None = None
    for attempt in range(1, _LOCK_RETRY_MAX_ATTEMPTS + 1):
        try:
            return duckdb.connect(str(path), read_only=read_only)
        except duckdb.IOException as exc:
            last_exc = exc
            if attempt < _LOCK_RETRY_MAX_ATTEMPTS:
                delay = _LOCK_RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                delay *= random.uniform(0.8, 1.2)  # nosec B311 - jitter, not crypto
                log.warning(
                    "historical.duckdb_lock_retry",
                    path=str(path),
                    attempt=attempt,
                    max_attempts=_LOCK_RETRY_MAX_ATTEMPTS,
                    delay_seconds=round(delay, 2),
                    error=str(exc),
                )
                time.sleep(delay)
    assert last_exc is not None  # loop always runs >=1 time
    raise last_exc


def _quote(name: str) -> str:
    return f'"{name}"'


def _resolve_path(db_path: Path | None) -> Path:
    """Resolve to an absolute path immediately -- a bare relative
    `historical_duckdb_path` would otherwise land wherever the calling
    process's cwd happens to be at write time (e.g. wherever `uvicorn`
    was launched from), which is easy to lose track of and doesn't match
    wherever a `duckdb` CLI session opened later happens to be launched
    from -- the exact bug already hit once in
    notebooks/feature_validation_standalone.ipynb's OUTPUT_DIR.
    """
    path = db_path if db_path is not None else get_settings().historical_duckdb_path
    return path.resolve()


def write_historical(
    source: str,
    docs: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    db_path: Path | None = None,
) -> int:
    """Upsert `docs` into the local DuckDB store for `source`.

    Stamps `ingest_run_id`/`fetched_at`/`source` onto every doc (mutated
    in place) before writing -- the same bookkeeping MongoDB's old
    `bulk_upsert` used to do as a side effect. Now that this is the sole
    write path (no Mongo write providing that stamping "for free"
    anymore), it has to happen here, or every table would silently be
    missing those columns. `run_id` defaults to a fresh uuid4 if the
    caller doesn't already have one to correlate with (e.g. a log line
    from earlier in the same ingest run).

    Idempotent on `IngestionSettings.unique_key_for_source(source)` -- a
    doc with a key already present overwrites in place rather than
    duplicating, so re-ingesting the same window twice is safe. Returns
    `len(docs)` (docs attempted) -- DuckDB's upsert doesn't cheaply
    distinguish inserted vs. updated rows, so this is a "docs processed"
    count, not a "net new rows" count.
    """
    if not docs:
        return 0

    path = _resolve_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    settings = get_ingestion_settings()
    table = settings.table_for_source(source)
    key_columns = settings.unique_key_for_source(source)

    run_id = run_id or uuid.uuid4().hex
    fetched_at = datetime.now(timezone.utc)
    for doc in docs:
        doc["ingest_run_id"] = run_id
        doc["fetched_at"] = fetched_at
        doc["source"] = source

    df = pd.DataFrame(docs)
    for col in df.columns:
        if df[col].map(lambda v: isinstance(v, datetime)).any():
            df[col] = pd.to_datetime(df[col], utc=True)

    con = _connect_with_retry(path, read_only=False)
    try:
        _upsert(con, table, df, key_columns)
    finally:
        con.close()

    log.info(
        "historical.duckdb_write",
        run_id=run_id,
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

    table = get_ingestion_settings().table_for_source(source)
    con = _connect_with_retry(path, read_only=True)
    try:
        exists = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()
        if not exists:
            return pd.DataFrame()
        return con.execute(f"SELECT * FROM {_quote(table)}").fetchdf()
    finally:
        con.close()


def read_historical_since(
    source: str,
    *,
    since: datetime | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Read rows for `source` with `fetched_at >= since` (all rows if
    `since` is None), as a list of plain dicts.

    Used by `warehouse/runner/postgres.py`'s `RawSyncer` to sync into
    Postgres `raw.*` -- unlike `read_historical` (whole-table DataFrame,
    meant for ad hoc/notebook use), this supports incremental filtering
    and returns row dicts directly so callers don't need a pandas
    dependency of their own.
    """
    path = _resolve_path(db_path)
    if not path.exists():
        return []

    table = get_ingestion_settings().table_for_source(source)
    con = _connect_with_retry(path, read_only=True)
    try:
        exists = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()
        if not exists:
            return []
        if since is not None:
            cursor = con.execute(
                f"SELECT * FROM {_quote(table)} WHERE fetched_at >= ?", [since]
            )
        else:
            cursor = con.execute(f"SELECT * FROM {_quote(table)}")
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        con.close()


def latest_fetched_at(
    source: str,
    *,
    db_path: Path | None = None,
) -> datetime | None:
    """Most recent `fetched_at` for `source`, or None if the store/table
    doesn't exist yet or has no rows.

    Used by `warehouse/runner/freshness.py`'s `SourceFreshnessChecker` to
    verify each source has recent data before running dbt on it.
    """
    path = _resolve_path(db_path)
    if not path.exists():
        return None

    table = get_ingestion_settings().table_for_source(source)
    con = _connect_with_retry(path, read_only=True)
    try:
        exists = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()
        if not exists:
            return None
        row = con.execute(f"SELECT max(fetched_at) FROM {_quote(table)}").fetchone()
        return row[0] if row is not None else None
    finally:
        con.close()


def count_by_day(
    source: str,
    field: str,
    start: _date,
    end: _date,
    *,
    db_path: Path | None = None,
) -> dict[_date, int]:
    """Row count per calendar day in `[start, end]` (inclusive) for
    `source`, bucketed by `field` (e.g. `"ts"` or `"date"`).

    Casts `field` to DATE/TIMESTAMP in SQL regardless of whether it's
    stored as a native temporal column or an ISO-8601 string (some
    sources' timestamp fields land as plain strings, not native types --
    `write_historical` only coerces columns holding actual `datetime`
    instances) -- DuckDB's CAST parses both uniformly, so callers don't
    need to track each source's field storage type. Days with zero rows
    are included as 0, not omitted, so gaps are visible rather than
    silently missing from the result.

    Used by `ingestion/api.py`'s `/ingestion/daily-counts` and
    `/ingestion/retry-missing`.
    """
    cast_type = "DATE" if field == "date" else "TIMESTAMP"
    full_range = {start + timedelta(days=i): 0 for i in range((end - start).days + 1)}

    path = _resolve_path(db_path)
    if not path.exists():
        return full_range

    table = get_ingestion_settings().table_for_source(source)
    con = _connect_with_retry(path, read_only=True)
    try:
        exists = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()
        if not exists:
            return full_range
        # The GROUP BY key is always CAST(... AS DATE) -- bucketing by
        # calendar day regardless of field type -- while the WHERE bounds
        # use `cast_type` (TIMESTAMP for a datetime-ish field, DATE for
        # an actual date field), matching the precision `start`/`end`
        # are given at. Using TIMESTAMP for the GROUP BY key here was a
        # real bug: two rows on the same day at different times of day
        # landed in separate groups instead of being counted together.
        rows = con.execute(
            f"""
            SELECT CAST({_quote(field)} AS DATE) AS day, count(*) AS n
            FROM {_quote(table)}
            WHERE CAST({_quote(field)} AS {cast_type}) >= ?
              AND CAST({_quote(field)} AS {cast_type}) < ?
            GROUP BY 1
            """,
            [start, end + timedelta(days=1)],
        ).fetchall()
    finally:
        con.close()

    for day, count in rows:
        day = day.date() if isinstance(day, datetime) else day
        full_range[day] = count
    return full_range


__all__ = [
    "write_historical",
    "read_historical",
    "read_historical_since",
    "count_by_day",
    "latest_fetched_at",
]
