"""DuckDB raw-landing staging (`overview.md` §1 Storage).

**Single shared file** (`Settings.duckdb_staging_dir/landed.duckdb`),
not one file per run — every ingest run appends into it rather than
creating a new file, per an explicit 2026-08-05 decision (matches the
root `TODO.md`'s original "one single duckdb, new data should be
append" storage plan, now applied to this service's own staging layer).
One real table per source (`bom_observations`, `aemo_nem_dispatch`,
...) inside that one file, each row tagged with the run that landed it
(`_ingest_run_id`) so a given run's rows stay identifiable/extractable
even though many runs now share one table.

This reverses the previous "one file per run" design, which existed
specifically because DuckDB only allows a single read-write connection
to a file at a time — the short-lived ingest process and the
long-running warehouse-sync consumer fighting over the same lock. That
tradeoff still exists here (this process still only holds the
connection open for the duration of one `stage_dataframe`/`read_staged`/
`delete_staged` call, same as before, to keep the lock window as short
as possible) — it wasn't solved, just accepted as the cost of a single
file. **Whichever service still runs `pipeline.warehouse_sync`'s
consumer needs a matching update** — `read_staged`/`delete_staged`
below now take `(path, table, run_id)`, not a bare `path`, since a path
alone no longer identifies one run's data.

`pipeline.tasks._common.standard_run` calls `stage_dataframe` right
after a successful fetch, then `upload_staged_file` (Phase 2, "Integrate
Cloudflare R2 Staging") to hand *just this run's rows* to object
storage — not the whole shared file, which would mean re-uploading the
service's entire history on every single run. `upload_staged_file`
extracts this run's subset into a small throwaway per-run `.duckdb`
snapshot (the old per-run file shape, `landed` table, no `_ingest_
run_id` column) purely for that upload, then discards it — the shared
file on disk is the only persistent local copy.
"""

from __future__ import annotations

import random
import tempfile
import time
from pathlib import Path

import duckdb
import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.service import object_storage

log = get_logger(__name__)

_TABLE = "landed"
_RUN_ID_COLUMN = "_ingest_run_id"

# `ingest_all_sources_task` (`pipeline.tasks.celery_tasks`) deliberately
# fans every source out as an independent parallel `celery.group` child
# so one slow source can't hold up the others -- real, live-confirmed
# 2026-08-07 side effect: when two or more finish fetching at close to
# the same moment, they race for DuckDB's single read-write lock on this
# shared file and the loser gets a hard `duckdb.IOException` ("Could not
# set lock on file... Conflicting lock is held"), not a queued wait.
# Retried here rather than fixed by serializing the fan-out itself --
# the parallelism across *fetches* (the slow, network-bound part) is
# still worth keeping; only the brief final write needs to not collide.
_LOCK_RETRY_ATTEMPTS = 5
_LOCK_RETRY_BASE_SECONDS = 0.5


def _connect_rw_with_retry(path: Path) -> duckdb.DuckDBPyConnection:
    """`duckdb.connect(path)` (read-write), retrying with jittered
    backoff if another process currently holds the file's single
    read-write lock, instead of failing the whole ingest run on what's
    usually a few hundred milliseconds of contention from a sibling
    source's own staging call."""
    last_error: duckdb.IOException | None = None
    for attempt in range(_LOCK_RETRY_ATTEMPTS):
        try:
            return duckdb.connect(str(path))
        except duckdb.IOException as exc:
            if "Conflicting lock" not in str(exc):
                raise
            last_error = exc
            sleep_seconds = _LOCK_RETRY_BASE_SECONDS * (2**attempt) + random.uniform(
                0, 0.25
            )
            log.warning(
                "duckdb_staging.lock_contention_retry",
                attempt=attempt + 1,
                max_attempts=_LOCK_RETRY_ATTEMPTS,
                sleep_seconds=round(sleep_seconds, 2),
            )
            time.sleep(sleep_seconds)
    assert last_error is not None  # noqa: S101 -- loop above always sets it before falling through
    raise last_error


def _staging_path() -> Path:
    settings = get_settings()
    return Path(settings.duckdb_staging_dir) / "landed.duckdb"


def staging_path() -> Path:
    """Public accessor for the shared staging file's path — `pipeline.
    retention`/`pipeline.ml_anomaly` both need it to open the same file
    this module writes to, without reaching into the private
    `_staging_path()`."""
    return _staging_path()


def read_table_history(table: str) -> pd.DataFrame:
    """Full accumulated history for one source's table, `_ingest_run_id`
    excluded — `pipeline.ml_anomaly.train`'s training data source (now
    genuinely queryable specifically *because* staging moved off
    one-file-per-run: a trained model needs more than one run's worth of
    rows). Empty if the shared file or `table` doesn't exist yet (a real,
    expected state before this source's second-ever run)."""
    path = _staging_path()
    if not path.exists():
        return pd.DataFrame()
    con = duckdb.connect(str(path), read_only=True)
    try:
        if not _table_exists(con, table):
            return pd.DataFrame()
        return con.execute(
            f"SELECT * EXCLUDE ({_RUN_ID_COLUMN}) FROM {table}"  # nosec B608 -- `table` is always a `registry.SOURCES` value, never user input
        ).df()
    finally:
        con.close()


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    result = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone()
    return bool(result and result[0] > 0)


def _add_missing_columns(
    con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame
) -> None:
    """Forward schema drift within one source over time (a later run's
    task code adds a column an earlier run's rows never had) is a real
    but rare case — the ingest tasks' own column sets are otherwise
    fixed per source, not per-run. `INSERT ... BY NAME` (used below)
    fails outright if `df` has a column the existing table doesn't, so
    this adds any missing ones first, typed from DuckDB's own inference
    over `df` rather than a hand-maintained pandas-dtype mapping.
    """
    existing = {row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()}  # nosec B608 -- `table` always comes from `registry.SOURCES`, never user input
    missing = [c for c in df.columns if c not in existing]
    if not missing:
        return

    con.register("_schema_probe", df)
    try:
        types_by_column = {
            row[0]: row[1] for row in con.execute("DESCRIBE _schema_probe").fetchall()
        }
        for col in missing:
            con.execute(
                f'ALTER TABLE {table} ADD COLUMN "{col}" {types_by_column[col]}'  # nosec B608 -- `table`/`col` come from `registry.SOURCES`/the ingest task's own fixed column set, never user input
            )
    finally:
        con.unregister("_schema_probe")


def stage_dataframe(df: pd.DataFrame, table: str, run_id: str) -> tuple[str, int]:
    """Append `df` into `table` inside the single shared staging file,
    tagging every row with `run_id`. Returns `(path, rows)` — `path` is
    always the same shared-file path now, not a per-run one.

    A no-op for an empty DataFrame — no write happens, `("", 0)` is
    returned — matching the old per-run behaviour (nothing worth landing
    or syncing).
    """
    if df.empty:
        return "", 0

    path = _staging_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    con = _connect_rw_with_retry(path)
    try:
        con.register("df_view", df)
        if _table_exists(con, table):
            _add_missing_columns(con, table, df)
            con.execute(
                f"INSERT INTO {table} BY NAME SELECT *, ? AS {_RUN_ID_COLUMN} FROM df_view",  # nosec B608 -- `table` is always a `registry.SOURCES` value, never user input
                [run_id],
            )
        else:
            con.execute(
                f"CREATE TABLE {table} AS SELECT *, ? AS {_RUN_ID_COLUMN} FROM df_view",  # nosec B608 -- `table` is always a `registry.SOURCES` value, never user input
                [run_id],
            )
    finally:
        con.close()

    return str(path), len(df)


def merge_staging_file(source_file: Path, table: str) -> int:
    """Merge another staging file's `table` into the canonical shared
    staging file, preserving each row's original `_ingest_run_id` as-is
    (no re-tagging — `source_file` already tagged them at write time).

    For a parallel per-source backfill that pointed `DUCKDB_STAGING_DIR`
    at its own scratch directory specifically to avoid DuckDB's
    single-writer lock on the canonical file (multiple processes can't
    hold a write connection to the same file at once) — this is the
    local, no-network reconciliation step afterward. Cheap: a DuckDB-to-
    DuckDB copy via pandas, no re-fetch from any external source.

    A no-op (`0`) if `source_file` doesn't exist or has no rows for
    `table` — safe to call speculatively.
    """
    if not source_file.exists():
        return 0

    src_con = duckdb.connect(str(source_file), read_only=True)
    try:
        if not _table_exists(src_con, table):
            return 0
        df = src_con.execute(f"SELECT * FROM {table}").df()  # nosec B608 -- `table` is always a `registry.SOURCES` value, never user input
    finally:
        src_con.close()

    if df.empty:
        return 0

    path = _staging_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    con = _connect_rw_with_retry(path)
    try:
        con.register("df_view", df)
        if _table_exists(con, table):
            _add_missing_columns(con, table, df)
            con.execute(
                f"INSERT INTO {table} BY NAME SELECT * FROM df_view"  # nosec B608 -- `table` is always a `registry.SOURCES` value, never user input
            )
        else:
            con.execute(
                f"CREATE TABLE {table} AS SELECT * FROM df_view"  # nosec B608 -- `table` is always a `registry.SOURCES` value, never user input
            )
    finally:
        con.close()

    return len(df)


def _staging_key(table: str, run_id: str) -> str:
    settings = get_settings()
    return f"{settings.object_storage_staging_prefix}/{table}-{run_id}.duckdb"


def _export_run_snapshot(path: str, table: str, run_id: str) -> Path:
    """Materialise just `run_id`'s rows from the shared file into a
    small, self-contained temp `.duckdb` file (old per-run shape — one
    `landed` table, no `_ingest_run_id` column) for `upload_staged_file`
    to hand to object storage. Uploading the shared file itself would
    mean re-uploading this service's entire local history on every
    single run.
    """
    rows_df = read_staged(path, table, run_id)

    tmp_path = Path(tempfile.gettempdir()) / f"{table}-{run_id}.duckdb"
    con = duckdb.connect(str(tmp_path))
    try:
        con.register("df_view", rows_df)
        con.execute(f"CREATE TABLE {_TABLE} AS SELECT * FROM df_view")  # nosec B608 -- `_TABLE` is a fixed module-level constant, not user input
    finally:
        con.close()
    return tmp_path


async def upload_staged_file(path: str, table: str, run_id: str) -> str | None:
    """Upload just-staged run's rows to object storage. Returns the
    object key (not the full `s3://` URI — `_common.standard_run`
    publishes the key/bucket separately in the RabbitMQ payload), or
    `None` for an empty-fetch run (`path == ""`, nothing to upload).

    Checks `object_storage.object_exists` first and skips the actual
    upload if the key is already there (`services/ingestion/TODO.md`
    Phase 2's "Verify Idempotency" item) — a run's `run_id` is always a
    fresh UUID, so this is defensive rather than expected to hit in
    practice, but it's the same "strict existence check before upload"
    idiom data-pipeline's own `scripts/upload_assets_to_r2.py` already
    uses.
    """
    if not path:
        return None

    key = _staging_key(table, run_id)
    if await object_storage.object_exists(key):
        log.info("duckdb_staging.upload_skipped_already_present", key=key)
        return key

    snapshot_path = _export_run_snapshot(path, table, run_id)
    try:
        uri = await object_storage.upload_file(snapshot_path, key)
    finally:
        snapshot_path.unlink(missing_ok=True)
    log.info("duckdb_staging.uploaded", key=key, uri=uri)
    return key


def read_staged(path: str, table: str, run_id: str) -> pd.DataFrame:
    """Read one run's rows back out of the shared staging file —
    `_ingest_run_id`-filtered, with that bookkeeping column itself
    excluded from the result (callers never asked for it; it's purely
    this module's own internal way of keeping runs apart within a
    shared table)."""
    con = duckdb.connect(path, read_only=True)
    try:
        return con.execute(
            f"SELECT * EXCLUDE ({_RUN_ID_COLUMN}) FROM {table} WHERE {_RUN_ID_COLUMN} = ?",  # nosec B608 -- `table` is always a `registry.SOURCES` value, never user input
            [run_id],
        ).df()
    finally:
        con.close()


def delete_staged(path: str, table: str, run_id: str) -> int:
    """Remove one run's rows from the shared staging file after they're
    safely in Postgres — never the file itself now (other runs' rows,
    possibly for other sources, live in it too). Returns the number of
    rows actually deleted (`pipeline.retention.prune_synced_history`
    uses this to report how much it actually freed up per source).

    Safe to call on an already-missing file, or a run whose rows are
    already gone (idempotent — a retried consumer run shouldn't blow up
    on cleanup that already happened) — returns `0` in both cases.
    """
    if not Path(path).exists():
        return 0
    con = _connect_rw_with_retry(Path(path))
    try:
        if not _table_exists(con, table):
            return 0
        result = con.execute(
            f"DELETE FROM {table} WHERE {_RUN_ID_COLUMN} = ?",  # nosec B608 -- `table` is always a `registry.SOURCES` value, never user input
            [run_id],
        )
        row = result.fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()
