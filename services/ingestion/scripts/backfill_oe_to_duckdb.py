#!/usr/bin/env python3
"""Backfill OpenElectricity generation mix + intensity (all 6 real
regions: NSW1/QLD1/VIC1/SA1/TAS1/WEM) for a real date range and write it
into its own **separate** local DuckDB file -- not the shared
`landed.duckdb` staging file `pipeline.tasks._common.standard_run`
writes into, and not routed through `meta._ingest_log`/
`publish_landed_event`/the warehouse sync at all. This is a standalone
local dump for ad-hoc analysis, not a pipeline run.

Reuses `ingest_openelectricity._fetch_historical_range` unchanged -- the
same real fetch `pipeline.backfill`/the CLI's `ingest openelectricity
--start/--end` already use (real OpenElectricity SDK calls, one calendar
day at a time -- that module's own docstring covers why: a single wide
multi-day query is O(n^2) in point count in the SDK's own `to_records()`
and took 86s live for just 3 days). Mirrors `backfill_nem_to_duckdb.py`/
`backfill_wem_to_duckdb.py` exactly, one source swapped for another.
Needs a real `OE_API_KEY` configured (`app/core/config.py`) -- the same
one `fetch_network_data`/`fetch_emissions` already require.

Day-chunked and awaited sequentially (not parallel) -- same as the real
ingest path -- so a wide range (e.g. 7 months) takes a while; run this in
the background.

Run from `services/ingestion/`:

    uv run python scripts/backfill_oe_to_duckdb.py \\
        --from 2025-01-01 --to 2025-07-31 \\
        --output data/historical_oe.duckdb
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path

import click
import duckdb

from app.core.logging import configure_logging, get_logger
from app.service.pipeline.tasks.ingest_openelectricity import _fetch_historical_range

log = get_logger(__name__)

_TABLE = "openelectricity_mix"


@click.command()
@click.option("--from", "date_from", required=True, help="Start date, YYYY-MM-DD (inclusive).")
@click.option("--to", "date_to", required=True, help="End date, YYYY-MM-DD (inclusive).")
@click.option(
    "--output",
    default="data/historical_oe.duckdb",
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

    log.info("backfill_oe_to_duckdb.starting", date_from=str(d_from), date_to=str(d_to))
    df = asyncio.run(_fetch_historical_range(start, end))

    if df.empty:
        log.warning("backfill_oe_to_duckdb.no_rows_fetched")
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
        "backfill_oe_to_duckdb.done",
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
