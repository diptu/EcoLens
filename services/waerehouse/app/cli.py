"""`ecolens-warehouse` console-script entrypoint.

Click group: `consume`, `prune`, `export-and-prune`, `vacuum`,
`check-size`, `health`, `serve`. `consume` is the long-running RabbitMQ
consumer (`docker-compose.yml`'s `warehouse-consumer` service /
`docker exec`); `prune`/`export-and-prune`/`vacuum`/`check-size` are
one-shot, manually/cron-triggered retention operations (README Phase
3's own "pg_cron or Celery Task" framing — this service doesn't
schedule itself, an operator/cron calls in), same conservative default
`services/ingestion`'s own `prune-staging`/`train-anomaly-model`
commands use.
"""

from __future__ import annotations

import asyncio

import click

from app import __version__
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


@click.group()
@click.version_option(__version__, prog_name="ecolens-warehouse")
def main() -> None:
    """ecoLens warehouse service CLI."""
    configure_logging()


# ── consume ──────────────────────────────────────────────────────────────


@main.command()
def consume() -> None:
    """Run the RabbitMQ landed-events consumer forever -- reads
    `Settings.rabbitmq_landing_queue`, syncs each message into Postgres
    `raw.*` (`consumers.landed_events.sync_landed_event`). Equivalent
    role to `data-pipeline`'s `ecolens-pipeline worker`, for this
    service's own narrower scope (sync only, no ML/dbt-trigger
    consumption)."""
    from app.consumers.landed_events import sync_landed_event
    from app.db.rabbitmq import consume_landed_events

    click.echo("warehouse consumer starting -- Ctrl+C to stop")
    try:
        asyncio.run(consume_landed_events(sync_landed_event))
    except KeyboardInterrupt:
        click.echo("warehouse consumer stopped")


# ── retention ────────────────────────────────────────────────────────────


@main.command()
@click.option(
    "--days", type=int, default=None, help="Override Settings.retention_days (60)."
)
def prune(days: int | None) -> None:
    """Delete raw.* rows older than --days, without exporting them to
    cold storage first. Prefer `export-and-prune` unless you're certain
    you don't need a durable copy of what's being deleted."""
    from app.retention.pruning import prune_raw_tables

    pruned = asyncio.run(prune_raw_tables(days))
    if not pruned:
        click.echo("Nothing eligible to prune.")
        return
    for table, rows in sorted(pruned.items()):
        click.echo(f"{table}: {rows} rows pruned")


@main.command("export-and-prune")
@click.option(
    "--days", type=int, default=None, help="Override Settings.retention_days (60)."
)
def export_and_prune_cmd(days: int | None) -> None:
    """Export each table's about-to-expire rows to R2 cold storage
    (Parquet), then delete them from Postgres -- only once the export
    has actually succeeded. The safe default (README Phase 3's own
    ordering); see `retention.cold_storage`'s own module docstring."""
    from app.retention.cold_storage import export_and_prune

    results = asyncio.run(export_and_prune(days))
    if not results:
        click.echo("Nothing eligible to export/prune.")
        return
    for table, counts in sorted(results.items()):
        click.echo(f"{table}: exported {counts['exported']}, pruned {counts['pruned']}")


@main.command()
def vacuum() -> None:
    """VACUUM ANALYZE the prunable raw.* tables -- run after a large
    prune to actually reclaim disk space (README Phase 3)."""
    from app.retention.vacuum import vacuum_analyze_raw_tables

    tables = asyncio.run(vacuum_analyze_raw_tables())
    click.echo(f"Vacuumed: {', '.join(tables)}")


@main.command("check-size")
def check_size() -> None:
    """Report current Postgres database size against the configured
    free-tier limit (README Phase 3's monitoring/alerting ask)."""
    from app.retention.size_monitor import check_database_size

    report = asyncio.run(check_database_size())
    mb_used = report.size_bytes / (1024 * 1024)
    mb_limit = report.limit_bytes / (1024 * 1024)
    click.echo(
        f"{mb_used:.1f} MB / {mb_limit:.0f} MB "
        f"({report.pct_used * 100:.1f}%) -- {report.severity}"
    )
    if report.severity != "ok":
        raise SystemExit(1)


# ── dbt ──────────────────────────────────────────────────────────────────


@main.command(context_settings={"ignore_unknown_options": True})
@click.argument("subcommand")
@click.option("--target", default="dev", help="dbt target (dev/prod).")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
def dbt(subcommand: str, target: str, extra_args: tuple[str, ...]) -> None:
    """Run a dbt subcommand against the ported `dbt/ecolens` project
    (README Phase 4). E.g. `ecolens-warehouse dbt run`, `ecolens-
    warehouse dbt test`, `ecolens-warehouse dbt source freshness`."""
    from app.dbt.runner import run_dbt

    exit_code, output = run_dbt(subcommand, target=target, extra_args=list(extra_args))
    click.echo(output)
    if exit_code != 0:
        raise SystemExit(exit_code)


# ── serve / health ──────────────────────────────────────────────────────


@main.command()
def health() -> None:
    """Liveness check — mirrors `GET /v1/healthz`'s response shape."""
    from app.schemas.health import HealthResponse

    click.echo(HealthResponse().model_dump_json())


@main.command()
@click.option("--host", default="0.0.0.0")  # nosec B104 -- must bind all interfaces to be reachable in a container
@click.option("--port", type=int, default=None)
@click.option("--reload", is_flag=True, default=False)
def serve(host: str, port: int | None, reload: bool) -> None:
    """Run the FastAPI app with uvicorn (equivalent to `uvicorn app.main:app`)."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app", host=host, port=port or settings.api_port, reload=reload
    )


if __name__ == "__main__":
    main()
