#!/usr/bin/env python3
"""Backfill AEMO NEM 5-min dispatch (demand + price, all 5 NEM regions)
for a real date range and write it into its own **separate** local
DuckDB file — not the shared `landed.duckdb` staging file `pipeline.
tasks._common.standard_run` writes into, and not routed through
`meta._ingest_log`/`publish_landed_event`/the warehouse sync at all.
This is a standalone local dump for ad-hoc analysis, not a pipeline run.

Reuses `ingest_aemo_nem._fetch_historical_range` unchanged -- the same
real fetch `pipeline.backfill`/the CLI's `ingest aemo-nem --start/--end`
already use, including its real MMSDM fallback (2026-08-12) for days
outside the live DispatchIS Archive's ~13-month retention window.

Run from `services/ingestion/`:

    uv run python scripts/backfill_nem_to_duckdb.py \\
        --from 2025-07-01 --to 2025-07-31 \\
        --output data/historical_nem.duckdb
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path

import click
import duckdb

from app.core.logging import configure_logging, get_logger
from app.service.pipeline.tasks.ingest_aemo_nem import _fetch_historical_range

log = get_logger(__name__)

_TABLE = "aemo_nem_dispatch"


@click.command()
@click.option("--from", "date_from", required=True, help="Start date, YYYY-MM-DD (inclusive).")
@click.option("--to", "date_to", required=True, help="End date, YYYY-MM-DD (inclusive).")
@click.option(
    "--output",
    default="data/historical_nem.duckdb",
    show_default=True,
    help="Path to the standalone output DuckDB file (created fresh if it doesn't exist).",
)
def main(date_from: str, date_to: str, output: str) -> None:
    configure_logging()
    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)
    if d_to < d_from:
        raise click.UsageError(f"--to ({d_to}) must be >= --from ({d_from})")

    start = datetime(d_from.year, d_from.month, d_from.day, tzinfo=timezone.utc)
    end = datetime(d_to.year, d_to.month, d_to.day, tzinfo=timezone.utc)

    log.info("backfill_nem_to_duckdb.starting", date_from=str(d_from), date_to=str(d_to))
    df = asyncio.run(_fetch_historical_range(start, end))

    if df.empty:
        log.warning("backfill_nem_to_duckdb.no_rows_fetched")
        click.echo("No rows fetched -- nothing written.")
        return

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(out_path))
    try:
        con.register("df_view", df)
        exists = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [_TABLE],
        ).fetchone()[0] > 0
        if exists:
            con.execute(f"INSERT INTO {_TABLE} BY NAME SELECT * FROM df_view")  # nosec B608 -- _TABLE is a fixed constant, never user input
        else:
            con.execute(f"CREATE TABLE {_TABLE} AS SELECT * FROM df_view")  # nosec B608 -- _TABLE is a fixed constant, never user input
        total_rows = con.execute(f"SELECT count(*) FROM {_TABLE}").fetchone()[0]  # nosec B608 -- _TABLE is a fixed constant, never user input
        regions = con.execute(f"SELECT DISTINCT region FROM {_TABLE} ORDER BY region").fetchall()  # nosec B608 -- _TABLE is a fixed constant, never user input
    finally:
        con.close()

    log.info(
        "backfill_nem_to_duckdb.done",
        rows_written=len(df),
        total_rows_in_table=total_rows,
        output=str(out_path),
    )
    click.echo(
        f"Wrote {len(df):,} rows ({d_from} → {d_to}) to {out_path} "
        f"(table: {_TABLE}, {total_rows:,} rows total, regions: "
        f"{[r[0] for r in regions]})"
    )


if __name__ == "__main__":
    main()
