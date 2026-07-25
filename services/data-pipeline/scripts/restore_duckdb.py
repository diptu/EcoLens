"""Restore a DuckDB snapshot produced by `scripts/backup_duckdb.py`.

Rebuilds a `.duckdb` file from a snapshot directory (Parquet + schema/
load SQL, written by `EXPORT DATABASE`) via `IMPORT DATABASE`. Refuses
to overwrite an existing target file unless `--force` is passed --
restoring is a rare, deliberate recovery action, and silently clobbering
whatever's currently at the target path would defeat the point of
having backups in the first place.

Run directly:

    # List available snapshots for the default DB path's backup dir
    uv run --active ./scripts/restore_duckdb.py --list

    # Restore the most recent snapshot into a fresh file
    uv run --active ./scripts/restore_duckdb.py --latest --target /path/to/restored.duckdb

    # Restore a specific snapshot
    uv run --active ./scripts/restore_duckdb.py --snapshot /path/to/backups/20260724T120000Z --target /path/to/restored.duckdb

    # Or via Makefile from the repo root:
    make restore-duckdb SNAPSHOT=20260724T120000Z [TARGET=/path/to/restored.duckdb]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

from ecolens.config import get_settings
from ecolens.shared.observability.logging import get_logger

log = get_logger("restore_duckdb")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="directory snapshots live in (default: <default db file's dir>/backups)",
    )
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument(
        "--list", action="store_true", help="list available snapshots and exit"
    )
    selector.add_argument(
        "--snapshot", type=Path, default=None, help="path to a specific snapshot dir"
    )
    selector.add_argument(
        "--snapshot-name",
        type=str,
        default=None,
        help="name of a snapshot inside --backup-dir (e.g. 20260724T120000Z, as shown by --list)",
    )
    selector.add_argument(
        "--latest",
        action="store_true",
        help="restore the most recent snapshot in --backup-dir",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="path to write the restored .duckdb file to (required unless --list)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite --target if it already exists",
    )
    args = parser.parse_args()

    if not args.list:
        if args.snapshot is None and args.snapshot_name is None and not args.latest:
            parser.error(
                "one of --list, --snapshot, --snapshot-name, or --latest is required"
            )
        if args.target is None:
            parser.error("--target is required unless --list")
    return args


def list_snapshots(backup_dir: Path) -> list[Path]:
    if not backup_dir.exists():
        return []
    return sorted((d for d in backup_dir.iterdir() if d.is_dir()), key=lambda d: d.name)


def restore(*, snapshot: Path, target: Path, force: bool = False) -> None:
    if not snapshot.exists():
        raise FileNotFoundError(f"snapshot dir does not exist: {snapshot}")
    if target.exists() and not force:
        raise FileExistsError(
            f"{target} already exists -- pass --force to overwrite, "
            "or pick a different --target"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    con = duckdb.connect(str(target))
    try:
        con.execute(f"IMPORT DATABASE '{snapshot}'")
    finally:
        con.close()


def main() -> None:
    args = parse_args()
    default_db_path = get_settings().historical_duckdb_path.resolve()
    backup_dir = (args.backup_dir or default_db_path.parent / "backups").resolve()

    if args.list:
        snapshots = list_snapshots(backup_dir)
        if not snapshots:
            print(f"No snapshots found in {backup_dir}")
            return
        print(f"Snapshots in {backup_dir}:")
        for s in snapshots:
            print(f"  {s.name}")
        return

    if args.latest:
        snapshots = list_snapshots(backup_dir)
        if not snapshots:
            print(f"No snapshots found in {backup_dir}")
            sys.exit(1)
        snapshot = snapshots[-1]
    elif args.snapshot_name is not None:
        snapshot = backup_dir / args.snapshot_name
    else:
        assert args.snapshot is not None
        snapshot = args.snapshot.resolve()

    target = args.target.resolve()
    print(f"Restoring {snapshot} -> {target}")
    try:
        restore(snapshot=snapshot, target=target, force=args.force)
    except (FileNotFoundError, FileExistsError) as exc:
        print(f"FAILED: {exc}")
        sys.exit(1)

    con = duckdb.connect(str(target), read_only=True)
    try:
        tables = con.sql("SHOW TABLES").df()["name"].tolist()
        print(f"Restored {len(tables)} table(s): {tables}")
    finally:
        con.close()

    log.info("restore_duckdb.complete", snapshot=str(snapshot), target=str(target))
    print(f"Restore complete: {target}")


if __name__ == "__main__":
    main()
