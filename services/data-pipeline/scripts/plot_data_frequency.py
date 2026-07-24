#!/usr/bin/env python3
"""Bar chart of daily row counts in ml_features_demand_v1 over a date range.

Answers "how much training data do we actually have per day?" -- the
same warehouse mart `training/data.py`'s TrainingSetLoader snapshots
for training reads from here directly, grouped by day, so gaps/thin
days show up before they surface as a training-data surprise.

Run from the data-pipeline venv (needs the `ecolens` package):

    cd services/data-pipeline
    uv run --active python scripts/plot_data_frequency.py \\
        --start-date 2026-01-01 --end-date 2026-07-01

    # Or via Makefile from the repo root:
    make plot-data-frequency START_DATE=2026-01-01 END_DATE=2026-07-01 [REGION=NSW1] [OUTPUT=path.png]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta
from pathlib import Path

import asyncpg
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from ecolens.shared.observability.logging import get_logger
from ecolens.warehouse.api.settings import get_warehouse_api_settings

log = get_logger("plot_data_frequency")

_QUERY = """
select date(ts_30) as day, count(*) as row_count
from ml_features_demand_v1
where ts_30 >= $1 and ts_30 < $2
{region_clause}
group by day
order by day
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        required=True,
        help="First day (inclusive), YYYY-MM-DD",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        required=True,
        help="Last day (inclusive), YYYY-MM-DD",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="Restrict to one region (e.g. NSW1). Default: all regions, summed.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="PNG output path. Default: reports/data_frequency_<start>_<end>.png",
    )
    args = parser.parse_args()
    if args.end_date < args.start_date:
        parser.error("--end-date must be on or after --start-date")
    return args


async def fetch_daily_counts(
    start: date, end: date, region: str | None
) -> pd.DataFrame:
    ws = get_warehouse_api_settings()
    if ws.pg_dsn:
        conn = await asyncpg.connect(
            dsn=ws.pg_dsn, timeout=ws.pg_command_timeout_seconds
        )
    else:
        conn = await asyncpg.connect(
            host=ws.pg_host,
            port=ws.pg_port,
            database=ws.pg_database,
            user=ws.pg_user,
            password=ws.pg_password,
            timeout=ws.pg_command_timeout_seconds,
        )
    try:
        # end is inclusive on the CLI, exclusive in the query (ts_30 < end + 1 day)
        params: list[object] = [start, end + timedelta(days=1)]
        region_clause = ""
        if region:
            region_clause = "and region = $3"
            params.append(region)
        rows = await conn.fetch(_QUERY.format(region_clause=region_clause), *params)
    finally:
        await conn.close()
    df = pd.DataFrame(rows, columns=["day", "row_count"])
    df["day"] = pd.to_datetime(df["day"])

    # Reindex over the full range so days with zero rows show as gaps
    # instead of silently disappearing from the chart.
    full_range = pd.date_range(start, end, freq="D")
    df = (
        df.set_index("day")
        .reindex(full_range, fill_value=0)
        .rename_axis("day")
        .reset_index()
    )
    return df


def plot(
    df: pd.DataFrame, start: date, end: date, region: str | None, output: Path
) -> None:
    fig, ax = plt.subplots(figsize=(max(10, len(df) * 0.15), 5))
    ax.bar(df["day"], df["row_count"], width=0.9, color="#2b7a78")
    title = f"ml_features_demand_v1 row count per day: {start} to {end}"
    if region:
        title += f" ({region})"
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("Row count")
    fig.autofmt_xdate()
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)


async def main() -> int:
    args = parse_args()
    output = args.output or Path(
        f"reports/data_frequency_{args.start_date}_{args.end_date}.png"
    )
    df = await fetch_daily_counts(args.start_date, args.end_date, args.region)
    plot(df, args.start_date, args.end_date, args.region, output)
    zero_days = int((df["row_count"] == 0).sum())
    log.info(
        "plot_data_frequency.done",
        days=len(df),
        zero_days=zero_days,
        total_rows=int(df["row_count"].sum()),
        output=str(output),
    )
    print(f"Wrote {output} ({len(df)} days, {zero_days} with zero rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
