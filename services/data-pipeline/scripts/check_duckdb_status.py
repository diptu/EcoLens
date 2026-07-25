"""Standalone health check for the local DuckDB historical store.

Diagnoses the single most common support question this store generates:
"I triggered /ingestion/historical, it reported success, but I don't see
the data in DuckDB" -- which is almost always one of:

  1. Another DuckDB connection (a `duckdb -ui` session, a plain CLI
     session, a stale notebook kernel) is holding the file's
     single-writer lock, so the write failed (logged at `error`
     server-side, but never surfaced in the job's API response --
     `write_historical` retries internally, but a long-held lock can
     still outlast those retries).
  2. The source fetch returned zero docs for the requested date/range, so
     DuckDB never got written to in the first place -- check the job's
     own `written` count first.
  3. The path resolved differently for the writer and whoever's looking
     (fixed by resolving to an absolute path -- see duckdb_store.py --
     but worth ruling out if running older code).

Run directly:

    uv run --active ./scripts/check_duckdb_status.py
    uv run --active ./scripts/check_duckdb_status.py --path /custom/path.duckdb
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

from ecolens.config import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="DuckDB file to check (default: Settings.historical_duckdb_path)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = (args.path or get_settings().historical_duckdb_path).resolve()

    print(f"Checking: {path}")
    if not path.exists():
        print("NOT FOUND -- nothing has ever written to this path.")
        print(
            "Trigger an ingest (POST /ingestion/historical or "
            "scripts/backfill_bom_historical.py) and check its job status "
            "for `upserted` > 0 first."
        )
        sys.exit(1)

    # A read-only open is NOT enough to dodge another connection's lock --
    # DuckDB's single-writer exclusivity blocks read-only opens too while
    # any read-write connection is active elsewhere. So this same open is
    # both the "list what's in there" step AND the lock check: if it
    # fails, the exception message already names the exact PID/binary
    # holding the lock (DuckDB prints it directly) -- that's almost
    # always the actual root cause of "my insert didn't land."
    try:
        con = duckdb.connect(str(path), read_only=True)
    except Exception as exc:  # noqa: BLE001 - diagnostic script, report and exit
        print(
            "FAILED to open (even read-only) -- this is very likely why inserts aren't landing:"
        )
        print(f"  {exc}")
        print(
            "Close whatever process that names (duckdb -ui, another CLI "
            "session, a stale notebook kernel), then re-trigger the ingest."
        )
        sys.exit(1)

    try:
        tables = con.sql("SHOW TABLES").df()["name"].tolist()
        if not tables:
            print("File exists but has no tables yet -- no source has written a row.")
        for table in tables:
            row = con.sql(
                f'SELECT count(*) AS n, max(fetched_at) AS last_write FROM "{table}"'
            ).fetchone()
            assert row is not None  # a count(*) query always returns exactly one row
            print(f"  {table:<28} rows={row[0]:<8} last_write={row[1]}")
    finally:
        con.close()
    print("\nNo lock conflict -- the file is currently writable.")


if __name__ == "__main__":
    main()
