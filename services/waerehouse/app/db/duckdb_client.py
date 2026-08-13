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

`read_run_with_fallback` handles the cross-machine case: `services/
ingestion` ran on a different host than this consumer, so the
`duckdb_staging` Docker volume they'd otherwise share isn't actually
shared — `staging_path()` just never exists locally. Ingestion's
producer always uploads the same run to object storage too
(`pipeline.duckdb_staging.upload_staged_file`) and publishes its
key/bucket alongside `duckdb_path` in the same event this service's
`consumers.landed_events` handles — that's the real, network-crossing
handoff, not the local volume.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import pandas as pd

from app.core.config import get_settings
from app.db import object_storage

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


def _read_snapshot_table(path: Path) -> pd.DataFrame:
    """Read a downloaded object-storage run-snapshot -- always a fixed
    `landed` table holding just that one run's rows already (`services/
    ingestion`'s `pipeline.duckdb_staging._export_run_snapshot`), no
    `_ingest_run_id` filtering needed the way the shared local file
    needs."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute("SELECT * FROM landed").df()  # nosec B608 -- fixed literal table name, not user input
    finally:
        con.close()


async def read_run_with_fallback(
    table: str,
    run_id: str,
    object_storage_key: str | None,
    object_storage_bucket: str | None,
) -> pd.DataFrame:
    """`read_run`, but downloads the run's object-storage snapshot when
    the shared staging file doesn't exist locally at all — see this
    module's own docstring for why that's the real cross-machine signal
    (as opposed to the file existing but this particular run's rows not
    being in it, e.g. an already-consumed redelivery — that stays
    `read_run`'s existing "empty, not an error" behaviour unchanged,
    re-loading the same rows from object storage in that case would just
    be a wasted round trip since `loaders.postgres_loader.
    load_to_postgres`'s `ON CONFLICT DO NOTHING` already makes a same-
    rows redelivery idempotent locally).

    `object_storage_key` being `None` (no object-storage info in the
    event — shouldn't happen for a `services/ingestion`-produced event,
    but defensive either way) falls through to plain `read_run`, so a
    missing local file with no fallback available still returns the
    same honest empty result it always did rather than raising a new
    error class here.
    """
    if staging_path().exists() or not object_storage_key:
        return read_run(table, run_id)

    tmp_path = Path(tempfile.gettempdir()) / f"remote-{table}-{run_id}.duckdb"
    body = await object_storage.download_bytes(object_storage_key, bucket=object_storage_bucket)
    tmp_path.write_bytes(body)
    try:
        return _read_snapshot_table(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
