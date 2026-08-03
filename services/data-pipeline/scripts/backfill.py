#!/usr/bin/env python3
"""CLI wrapper for `app.service.pipeline.backfill` — that module has the
actual logic; see it and `pipeline/tasks/task.md`'s "Failure Modes &
Recovery" section for the operational context this exists for.

Run from `services/data-pipeline/` so the workspace/package resolves:

    uv run --package data-pipeline python scripts/backfill.py \\
        --from 2026-07-19 --to 2026-07-19

    uv run --package data-pipeline python scripts/backfill.py \\
        --source bom --from 2026-07-13 --to 2026-07-19

    uv run --package data-pipeline python scripts/backfill.py \\
        --source aemo-nem --from 2026-07-19 --to 2026-07-19 --lookback-minutes 1440
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import click

from app.core.config import get_settings
from app.service.dbt_runner import run_dbt
from app.core.logging import configure_logging
from app.service.pipeline.backfill import (
    BACKFILLABLE_SOURCES,
    DEFAULT_LOOKBACK_MINUTES,
    backfill,
)


@click.command()
@click.option(
    "--from", "from_", required=True, type=click.DateTime(formats=["%Y-%m-%d"])
)
@click.option("--to", "to_", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option(
    "--source",
    "sources",
    type=click.Choice(BACKFILLABLE_SOURCES),
    multiple=True,
    help="Repeatable. Defaults to all backfillable sources.",
)
@click.option("--lookback-minutes", type=int, default=DEFAULT_LOOKBACK_MINUTES)
@click.option(
    "--skip-dbt", is_flag=True, default=False, help="Don't run `dbt build` at the end."
)
def main(
    from_: datetime,
    to_: datetime,
    sources: tuple[str, ...],
    lookback_minutes: int,
    skip_dbt: bool,
) -> None:
    """Backfill missing days for one or more ingestion sources."""
    configure_logging()

    start, end = from_.date(), to_.date()
    if start > end:
        raise click.UsageError(f"--from ({start}) must not be after --to ({end})")

    selected = sources or BACKFILLABLE_SOURCES

    results = asyncio.run(backfill(selected, start, end, lookback_minutes))
    for (source, day), outcome in results.items():
        click.echo(f"{day} {source}: {outcome}")

    failures = [key for key, outcome in results.items() if outcome.startswith("failed")]

    if not skip_dbt:
        settings = get_settings()
        click.echo("Running dbt build...")
        exit_code = run_dbt("build", settings.dbt_project_dir, settings.dbt_target)
        if exit_code != 0:
            click.echo(f"dbt build failed (exit code {exit_code})", err=True)

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
