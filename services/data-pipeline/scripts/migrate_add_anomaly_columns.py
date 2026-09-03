"""One-off schema migration: adds `anomaly_score`/`anomaly_flags`/
`anomaly_explanation`/`created_at` to every existing DuckDB source table.

Root TODO.md's "Anomaly Detection" section: `duckdb_store.py`'s
`_upsert()` only defines a table's columns on its *first-ever* write
(`CREATE TABLE ... AS SELECT * FROM df LIMIT 0`) -- all 5 source tables
already exist in any environment that's been ingesting before this
feature shipped, so `write_historical()` stamping the 3 new anomaly
columns onto every doc would otherwise break every subsequent
`INSERT INTO t SELECT * FROM df` with a column-count mismatch the moment
the anomaly-scoring code (`ingestion/service/anomaly/`) started running.
Run this once against any existing store before that code ships against
it. A brand-new store (no prior tables) doesn't need this at all --
`_upsert()` already creates a first-ever table with whatever columns the
first-written docs carry, anomaly columns included.

Idempotent (`ADD COLUMN IF NOT EXISTS`) -- safe to run against a store
that's already been migrated, or one that's never been ingested into at
all (a source's table simply doesn't exist yet, logged and skipped, not
an error).

Usage:
    uv run --active ./scripts/migrate_add_anomaly_columns.py
    uv run --active ./scripts/migrate_add_anomaly_columns.py --path /custom/path.duckdb

    # Or via Makefile from the repo root:
    make migrate-anomaly-columns
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ecolens.config import get_settings
from ecolens.ingestion.core.settings import get_ingestion_settings
from ecolens.ingestion.db.duckdb_store import _connect_with_retry, _quote
from ecolens.shared.observability.logging import get_logger

log = get_logger("migrate_add_anomaly_columns")

# (column, DuckDB type) -- anomaly_flags/anomaly_explanation are plain
# VARCHAR (delimited text), not a native LIST type -- see
# ingestion/service/anomaly/scorer.py's module docstring for why:
# portability across DuckDB -> Postgres raw.* -> dbt without needing
# array-handling machinery on any of those hops. `created_at` is the UTC
# instant `score_batch()` last (re-)scored the row, not its original
# ingest time (`ingested_at`/`fetched_at` already cover that).
_NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("anomaly_score", "DOUBLE"),
    ("anomaly_flags", "VARCHAR"),
    ("anomaly_explanation", "VARCHAR"),
    ("created_at", "TIMESTAMP"),
)

_ALL_SOURCES: tuple[str, ...] = (
    "openelectricity",
    "aemo_nem",
    "aemo_wem",
    "bom",
    "aemo_holidays",
)


def migrate(db_path: Path) -> list[str]:
    """Ensures `_NEW_COLUMNS` exist on every source table found in
    `db_path`. Returns the list of tables actually touched (existed and
    got at least attempted) -- a source whose table doesn't exist yet is
    skipped, not an error (nothing to migrate: its first real write will
    create the table with the anomaly columns already included).
    """
    settings = get_ingestion_settings()
    migrated: list[str] = []
    con = _connect_with_retry(db_path, read_only=False)
    try:
        for source in _ALL_SOURCES:
            table = settings.table_for_source(source)
            exists = con.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
                [table],
            ).fetchone()
            if not exists:
                log.info("migrate.table_not_found", source=source, table=table)
                continue
            for column, col_type in _NEW_COLUMNS:
                con.execute(
                    f"ALTER TABLE {_quote(table)} "
                    f"ADD COLUMN IF NOT EXISTS {_quote(column)} {col_type}"
                )
            log.info("migrate.table_migrated", source=source, table=table)
            migrated.append(table)
    finally:
        con.close()
    return migrated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="DuckDB file path (default: Settings.historical_duckdb_path)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = (args.path or get_settings().historical_duckdb_path).resolve()
    if not db_path.exists():
        print(f"No DuckDB store found at {db_path} -- nothing to migrate.")
        return 0

    migrated = migrate(db_path)
    if migrated:
        print(
            f"Anomaly columns ensured on {len(migrated)} table(s): {', '.join(migrated)}"
        )
    else:
        print("No existing source tables found -- nothing to migrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
