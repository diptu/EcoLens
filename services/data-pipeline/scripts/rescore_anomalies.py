"""One-off (or periodic) full rescore: recomputes `anomaly_score`/
`anomaly_flags`/`anomaly_explanation`/`created_at` for every existing
row in every source's DuckDB table, then writes back just those 4
columns -- unlike `duckdb_store.write_historical()`, this never touches
`ingest_run_id`/`fetched_at`/`source`, since those describe the row's
original ingest, not this rescoring pass.

Routine ingestion already scores every doc as it's written
(`write_historical` -> `anomaly.scorer.score_batch`) -- this script is
only for retroactively re-scoring rows that predate a change to the
scoring logic itself (a new rule, a new/retrained IsolationForest
model, a changed baseline setting, or -- ING/ECO anomaly-table
`created_at` rollout -- adding a column the scorer now stamps that
older rows never got).

`--clear-only` nulls the 4 columns without recomputing them (useful to
verify the "before" state, or as a standalone reset). Default (no
flag) clears then immediately rescores, so a run always leaves every
row with a fresh score rather than a gap.

Run directly:

    uv run --active ./scripts/rescore_anomalies.py
    uv run --active ./scripts/rescore_anomalies.py --source aemo_nem
    uv run --active ./scripts/rescore_anomalies.py --clear-only

    # Or via Makefile from the repo root:
    make rescore-anomalies [SOURCE=aemo_nem] [CLEAR_ONLY=1]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ecolens.config import get_settings
from ecolens.ingestion.core.settings import get_ingestion_settings
from ecolens.ingestion.db import duckdb_store
from ecolens.ingestion.db.duckdb_store import _connect_with_retry, _quote
from ecolens.ingestion.service.anomaly.scorer import score_batch
from ecolens.shared.observability.logging import get_logger

log = get_logger("rescore_anomalies")

_ALL_SOURCES: tuple[str, ...] = (
    "openelectricity",
    "aemo_nem",
    "aemo_wem",
    "bom",
    "aemo_holidays",
)

_ANOMALY_COLUMNS: tuple[str, ...] = (
    "anomaly_score",
    "anomaly_flags",
    "anomaly_explanation",
    "created_at",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source",
        choices=_ALL_SOURCES,
        default=None,
        help="rescore only this source (default: all 5)",
    )
    parser.add_argument(
        "--clear-only",
        action="store_true",
        help="null the 4 anomaly columns and stop -- don't recompute them",
    )
    return parser.parse_args()


def _table_exists(con, table: str) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()
        is not None
    )


def clear_columns(db_path: Path, sources: list[str]) -> list[str]:
    """Nulls `_ANOMALY_COLUMNS` on every row of each source's table.
    Returns the tables actually touched (existed) -- mirrors
    `migrate_add_anomaly_columns.migrate()`'s "skip, don't error" shape
    for a source whose table doesn't exist yet.
    """
    settings = get_ingestion_settings()
    cleared: list[str] = []
    con = _connect_with_retry(db_path, read_only=False)
    try:
        for source in sources:
            table = settings.table_for_source(source)
            if not _table_exists(con, table):
                log.info("rescore.table_not_found", source=source, table=table)
                continue
            set_clause = ", ".join(f"{_quote(c)} = NULL" for c in _ANOMALY_COLUMNS)
            con.execute(f"UPDATE {_quote(table)} SET {set_clause}")
            cleared.append(table)
            log.info("rescore.cleared", source=source, table=table)
    finally:
        con.close()
    return cleared


def rescore_source(source: str, db_path: Path) -> int:
    """Recomputes the 4 anomaly columns for every row of `source`'s
    table and writes them back in place, keyed on
    `IngestionSettings.unique_key_for_source(source)` -- every other
    column (including `ingest_run_id`/`fetched_at`) is left untouched.
    """
    settings = get_ingestion_settings()
    table = settings.table_for_source(source)
    key_columns = settings.unique_key_for_source(source)

    docs = duckdb_store.read_historical_since(source, since=None, db_path=db_path)
    if not docs:
        log.info("rescore.no_rows", source=source, table=table)
        return 0

    # Mutates every doc in place with fresh anomaly_score/anomaly_flags/
    # anomaly_explanation/created_at -- same function routine ingestion
    # calls, just over the whole table instead of one ingest batch.
    score_batch(source, docs, db_path=db_path)

    updates = pd.DataFrame(
        [
            {
                **{k: doc.get(k) for k in key_columns},
                **{c: doc.get(c) for c in _ANOMALY_COLUMNS},
            }
            for doc in docs
        ]
    )

    con = _connect_with_retry(db_path, read_only=False)
    try:
        set_clause = ", ".join(
            f"{_quote(c)} = u.{_quote(c)}" for c in _ANOMALY_COLUMNS
        )
        join_clause = " AND ".join(
            f"t.{_quote(k)} = u.{_quote(k)}" for k in key_columns
        )
        # `updates` is referenced by variable name in the FROM clause --
        # DuckDB's replacement scan picks up the local pandas DataFrame
        # directly, same pattern duckdb_store._upsert already uses for
        # `df`.
        con.execute(
            f"UPDATE {_quote(table)} AS t SET {set_clause} "
            f"FROM updates AS u WHERE {join_clause}"
        )
    finally:
        con.close()

    flagged = sum(1 for d in docs if d.get("anomaly_score", 0.0) > 0.0)
    log.info(
        "rescore.complete", source=source, table=table, rows=len(docs), flagged=flagged
    )
    return len(docs)


def main() -> int:
    args = parse_args()
    db_path = get_settings().historical_duckdb_path.resolve()
    if not db_path.exists():
        print(f"No DuckDB store found at {db_path} -- nothing to rescore.")
        return 0

    sources = [args.source] if args.source else list(_ALL_SOURCES)

    cleared = clear_columns(db_path, sources)
    print(f"cleared anomaly columns on {len(cleared)} table(s): {', '.join(cleared)}")
    if args.clear_only:
        return 0

    total = 0
    for source in sources:
        total += rescore_source(source, db_path)
    print(f"rescored {total} row(s) across {len(sources)} source(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
