"""Point-in-time backup for the historical DuckDB store.

DuckDB is now the *sole* raw store (MongoDB removed -- see root
TODO.md ECO-159): there is no remote redundant copy anymore, so losing
or corrupting the local `.duckdb` file means losing raw ingestion
history outright, with no fallback to re-derive it from. This script
takes a consistent snapshot via `EXPORT DATABASE` (Parquet + schema/
load SQL), which:

  - only needs a read-only connection, so it never corrupts/blocks the
    live writer -- but it IS still subject to DuckDB's single-writer
    file lock (a read-only open blocks while any read-write connection
    is active elsewhere, confirmed empirically -- not just "advisory"),
    so this reuses `duckdb_store`'s lock-retry-with-backoff connection
    helper rather than a bare `duckdb.connect(read_only=True)`.
  - is transactionally consistent -- a snapshot as of one point in
    time, not a raw file copy that could tear mid-write if it raced a
    writer between fsyncs.
  - is portable/inspectable -- plain Parquet + SQL files, not a
    DuckDB-version-locked binary `.duckdb` file, so a snapshot from an
    older DuckDB version can still be inspected/imported later.

Restoring: `scripts/restore_duckdb.py`.

Run directly, or on a schedule (cron / CI):

    uv run --active ./scripts/backup_duckdb.py
    uv run --active ./scripts/backup_duckdb.py --keep 30
    uv run --active ./scripts/backup_duckdb.py --path /custom/path.duckdb --backup-dir /custom/backups

    # Or via Makefile from the repo root:
    make backup-duckdb [KEEP=30]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from ecolens.config import get_settings
from ecolens.ingestion.db.duckdb_store import _connect_with_retry
from ecolens.shared.observability.logging import get_logger

log = get_logger("backup_duckdb")

_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_DEFAULT_KEEP = 14


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="DuckDB file to back up (default: Settings.historical_duckdb_path)",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="directory to write snapshots into (default: <db file's dir>/backups)",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=_DEFAULT_KEEP,
        help=f"number of most-recent snapshots to retain, older ones are deleted (default: {_DEFAULT_KEEP})",
    )
    return parser.parse_args()


def backup(*, path: Path, backup_dir: Path, keep: int) -> Path:
    """Snapshot `path` into a fresh timestamped directory under `backup_dir`.

    Returns the snapshot directory. Raises if `path` doesn't exist --
    there's nothing to back up, and silently no-op-ing that would make
    an empty/misconfigured source look identical to "backed up, zero
    rows" in a monitoring dashboard.
    """
    if not path.exists():
        raise FileNotFoundError(f"nothing to back up -- {path} does not exist")

    timestamp = datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)
    snapshot_dir = backup_dir / timestamp
    if snapshot_dir.exists():
        raise FileExistsError(
            f"snapshot dir already exists: {snapshot_dir} (two backups in the same second?)"
        )
    backup_dir.mkdir(parents=True, exist_ok=True)

    con = _connect_with_retry(path, read_only=True)
    try:
        con.execute(f"EXPORT DATABASE '{snapshot_dir}' (FORMAT PARQUET)")
    finally:
        con.close()

    _prune_old_snapshots(backup_dir, keep=keep)
    return snapshot_dir


def _prune_old_snapshots(backup_dir: Path, *, keep: int) -> list[Path]:
    """Delete all but the `keep` most-recent snapshot dirs (by name, which
    sorts chronologically since snapshots are named by UTC timestamp).
    Returns the list of dirs removed.
    """
    snapshots = sorted(
        (d for d in backup_dir.iterdir() if d.is_dir()), key=lambda d: d.name
    )
    stale = snapshots[:-keep] if keep > 0 else snapshots
    for d in stale:
        shutil.rmtree(d)
    return stale


def main() -> None:
    args = parse_args()
    path = (args.path or get_settings().historical_duckdb_path).resolve()
    backup_dir = (args.backup_dir or path.parent / "backups").resolve()

    print(f"Backing up: {path}")
    print(f"Snapshot dir: {backup_dir}")
    try:
        snapshot_dir = backup(path=path, backup_dir=backup_dir, keep=args.keep)
    except FileNotFoundError as exc:
        print(f"FAILED: {exc}")
        sys.exit(1)

    remaining = sorted(d.name for d in backup_dir.iterdir() if d.is_dir())
    log.info(
        "backup_duckdb.complete",
        path=str(path),
        snapshot=str(snapshot_dir),
        snapshots_retained=len(remaining),
    )
    print(f"Snapshot written: {snapshot_dir}")
    print(f"Snapshots retained ({len(remaining)}, keep={args.keep}): {remaining}")


if __name__ == "__main__":
    main()
