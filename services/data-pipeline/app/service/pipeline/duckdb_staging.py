"""DuckDB raw-landing staging (`overview.md` §1 Storage).

This service's own ingest tasks still stage their fetched DataFrame in
their own `.duckdb` file under `Settings.duckdb_staging_dir` —
`pipeline.tasks._common.standard_run` calls `stage_dataframe` right
after a successful fetch, one file per run. But `pipeline.
warehouse_sync`'s RabbitMQ consumer (`read_staged`/`delete_staged`
below) now has to handle **two** on-disk shapes, not just this service's
own:

1. **Legacy — this service's own producer** (`stage_dataframe` below):
   one file per run, a single fixed `landed` table, no run/source
   disambiguation column needed (the file only ever holds one run).
2. **`services/ingestion`'s producer** (`services/ingestion/app/
   service/pipeline/duckdb_staging.py`, 2026-08-05 redesign): a single
   *shared* `landed.duckdb` file, one real per-source table (named
   `table`, e.g. `bom_observations`) that many runs append into, rows
   tagged `_ingest_run_id` so one run's data stays extractable.

Both producers publish the identical `publish_landed_event` payload
shape (`run_id`/`source`/`table`/`schema`/`duckdb_path`) — the consumer
can't tell which shape a given `duckdb_path` is in from the payload
alone, so `read_staged`/`delete_staged` check the file itself (does a
`landed` table exist?) rather than trusting a hint that doesn't exist
yet. `services/ingestion/TODO.md`'s "Bridge Legacy Handoffs" note is
what tracks this — once this service's own legacy ingest tasks are
decommissioned (Phase 6, not started), the `landed`-table branch below
can go away and this whole module can be deleted in favour of always
reading the shared-file shape.

`services/ingestion`'s producer *also* publishes `object_storage_key`/
`object_storage_bucket` alongside `duckdb_path` (its own `_common.
standard_run` uploads every run's staged rows to R2/MinIO in addition
to writing them locally). This service's own legacy producer never
does — it has no object-storage upload step at all, so those two
payload fields are always absent from its events, and it's always
same-host with its own consumer by definition (one service, one
process pair). `read_staged_with_fallback` below is what makes cross-
machine deployment of `services/ingestion` actually work: today's root
`docker-compose.yml` only works because `ingestion`/`data-pipeline`
happen to share one Docker-local `duckdb_staging` volume on one host —
move `ingestion` to a different machine and that volume isn't shared
anymore, so the local file this consumer expects at `duckdb_path` just
isn't there. Object storage (a real network service, not a local
mount) is what actually crosses that machine boundary.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import pandas as pd

from app.core.config import get_settings
from app.service import object_storage

_TABLE = "landed"
_RUN_ID_COLUMN = "_ingest_run_id"


def _staging_path(table: str, run_id: str) -> Path:
    settings = get_settings()
    return Path(settings.duckdb_staging_dir) / f"{table}-{run_id}.duckdb"


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    result = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()
    return bool(result and result[0] > 0)


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


def read_staged(path: str, table: str, run_id: str) -> pd.DataFrame:
    """Read a staged run's DataFrame back out of its DuckDB file — either
    on-disk shape (see this module's own docstring). Tries the legacy
    fixed `landed` table first (this service's own producer, still the
    common case while its legacy ingest tasks are still active); falls
    back to the shared-file shape (`table`, `_ingest_run_id`-filtered)
    only if `landed` isn't there.
    """
    con = duckdb.connect(path, read_only=True)
    try:
        if _table_exists(con, _TABLE):
            return con.execute(f"SELECT * FROM {_TABLE}").df()  # nosec B608 -- `_TABLE` is a fixed module-level constant, not user input
        return con.execute(
            f"SELECT * EXCLUDE ({_RUN_ID_COLUMN}) FROM {table} WHERE {_RUN_ID_COLUMN} = ?",  # nosec B608 -- `table` always comes from the RabbitMQ payload's own `table` field, sourced from `registry.SOURCES`, never user input
            [run_id],
        ).df()
    finally:
        con.close()


async def read_staged_with_fallback(
    path: str,
    table: str,
    run_id: str,
    object_storage_key: str | None,
    object_storage_bucket: str | None,
) -> pd.DataFrame:
    """`read_staged`, but downloads the run's object-storage snapshot
    first when `path` doesn't exist locally — the cross-machine case
    (see this module's own docstring): `services/ingestion` ran on a
    different host than this consumer, so the `duckdb_staging` Docker
    volume they'd otherwise share isn't actually shared.

    `object_storage_key`/`_bucket` being `None` (this service's own
    legacy producer never populates them) just means the local-file
    branch below is the only one ever exercised for that producer's
    events — same as before this function existed. If the local file is
    genuinely missing with no object-storage fallback available either,
    delegates to `read_staged` so the caller sees the same real,
    honest "file not found" failure it always would have, rather than
    a different error invented here.

    Ingestion's object-storage snapshot is already the "legacy" `landed`-
    table shape (`services/ingestion/app/service/pipeline/duckdb_staging.
    py`'s `_export_run_snapshot` — just this run's rows, no `_ingest_
    run_id` column) — `read_staged` already handles that shape via its
    own first branch, so no new SQL/table-shape logic is needed here,
    only the download-to-a-real-local-file step DuckDB itself requires
    (it can't open a database directly from an in-memory byte buffer).
    """
    if Path(path).exists() or not object_storage_key:
        return read_staged(path, table, run_id)

    tmp_path = Path(tempfile.gettempdir()) / f"remote-{table}-{run_id}.duckdb"
    body = await object_storage.download_bytes(object_storage_key, bucket=object_storage_bucket)
    tmp_path.write_bytes(body)
    try:
        return read_staged(str(tmp_path), table, run_id)
    finally:
        tmp_path.unlink(missing_ok=True)


def delete_staged(path: str, table: str, run_id: str) -> None:
    """Remove a staged run's data after it's safely in Postgres — either
    on-disk shape (see this module's own docstring).

    Legacy shape (fixed `landed` table, one file per run): deletes the
    whole file, same as before — it only ever holds this one run.
    Shared-file shape (`services/ingestion`'s producer): deletes just
    this run's rows from `table`, never the file itself — other runs',
    possibly other sources', rows live in it too.

    Safe to call on an already-missing file, or a run whose rows are
    already gone (idempotent — a retried consumer run shouldn't blow up
    on cleanup that already happened).
    """
    if not Path(path).exists():
        return

    legacy = False
    con = duckdb.connect(path)
    try:
        legacy = _table_exists(con, _TABLE)
        if not legacy and _table_exists(con, table):
            con.execute(
                f"DELETE FROM {table} WHERE {_RUN_ID_COLUMN} = ?",  # nosec B608 -- `table` always comes from the RabbitMQ payload's own `table` field, sourced from `registry.SOURCES`, never user input
                [run_id],
            )
    finally:
        con.close()

    if legacy:
        Path(path).unlink(missing_ok=True)
