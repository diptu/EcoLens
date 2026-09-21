"""`ecolens-ingestion` console-script entrypoint.

Click group: `ingest {oe,aemo-nem,aemo-wem,bom,holidays}`, `backfill`,
`prune-staging`, `merge-staging`, `train-anomaly-model`, `worker`, `beat`,
`health`, `serve`. This is what cron/GitHub Actions/`docker exec` call — the same
code path as the matching API endpoint (`POST /v1/data-sources/{id}/
run`, `.../backfill`), via `app.service.pipeline.tasks.registry.
run_source` / `app.service.pipeline.backfill.backfill`.

Scoped down from data-pipeline's identical `ecolens-pipeline` CLI: no
`dbt`/`train`/`train-tft`/`tune`/`tune-optuna`/`evaluate*`/`auth`
groups — none of that is this service's job (`pyproject.toml`'s own
description). `prune-staging` and `train-anomaly-model` are **not**
that `train`/`prune` machinery ported over — `prune-staging` is local
DuckDB-file retention (`pipeline.retention`), not model pruning;
`train-anomaly-model` fits one lightweight isolation-forest model per
source for `pipeline.anomaly`'s own hybrid detection (`pipeline.
ml_anomaly`), nothing like data-pipeline's LSTM/TFT demand-forecasting
training pipeline. Unlike data-pipeline's `worker`/`train-worker`
(long-running RabbitMQ *consumers*), this service's `worker`/`beat`
*dispatch* scheduled ingestion via Celery (`app.celery_app`) — this
service still never consumes landed events itself. `ingest`'s
`--triggered-by schedule` also doesn't check `meta.pipelines` for a
paused source the way data-pipeline's does — that pause/resume admin
feature (`app.service.pipelines`) wasn't ported either, same
"trigger-only for now" scoping decision as `api/v1/datasources/
routes.py`'s module docstring.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

import click

from app import __version__
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.tracing import configure_tracing
from app.service.pipeline.backfill import (
    BACKFILLABLE_SOURCES,
    DEFAULT_LOOKBACK_MINUTES,
    backfill as run_backfill_range,
)
from app.service.pipeline.tasks.registry import SOURCES, run_source

log = get_logger(__name__)


@click.group()
@click.version_option(__version__, prog_name="ecolens-ingestion")
@click.pass_context
def main(ctx: click.Context) -> None:
    """ecoLens ingestion service CLI."""
    configure_logging()
    # `worker`'s Celery prefork pool forks child processes from this one
    # (`celery_app.start(["worker", ...])` runs the worker in-process, not
    # via a fresh `exec`) -- configuring tracing here first would mean
    # forking with a live gRPC exporter channel/background export thread
    # already open, which doesn't survive `fork()` safely (the same class
    # of bug `celery_app.py`'s own `_worker_loop` docstring already found
    # and fixed for asyncio event loops). `celery_app.py`'s
    # `worker_process_init` handler configures tracing fresh in each
    # forked child instead. Every other command (including `beat`, a
    # single long-running scheduler process, never a prefork pool) is one
    # process for its whole lifetime, so configuring here is correct for
    # them.
    if ctx.invoked_subcommand != "worker":
        configure_tracing()


# ── ingest ───────────────────────────────────────────────────────────────


@main.group()
def ingest() -> None:
    """Trigger an ingestion source (same path `run_source()` uses for the API)."""


def _run_ingest(key: str, *, triggered_by: str = "manual", **kwargs: object) -> None:
    call_kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        rows = asyncio.run(
            run_source(key, triggered_by=triggered_by, **call_kwargs)  # type: ignore[arg-type]
        )
    except Exception as exc:
        click.echo(f"{key}: failed — {exc}", err=True)
        sys.exit(1)
    click.echo(f"{key}: {rows} rows staged (warehouse sync runs asynchronously)")


_TRIGGERED_BY_OPTION = click.option(
    "--triggered-by",
    type=click.Choice(["manual", "schedule", "backfill", "shadow"]),
    default="manual",
    help="Recorded on meta._ingest_log. 'shadow' (Phase 4's \"Execute "
    'Shadow Runs") publishes to the shadow landing queue instead of the '
    "real one -- everything else (fetch, anomaly-scan, stage, meta."
    "_ingest_log row) happens for real, so scripts/verify_shadow_parity.py "
    "can compare it against a real run's outcome without the real "
    "warehouse-sync consumer ever double-loading raw.* from it.",
)


@ingest.command("oe")
@click.option("--lookback-minutes", type=int, default=None)
@_TRIGGERED_BY_OPTION
def ingest_oe(lookback_minutes: int | None, triggered_by: str) -> None:
    _run_ingest("oe", triggered_by=triggered_by, lookback_minutes=lookback_minutes)


@ingest.command("aemo-nem")
@click.option("--lookback-minutes", type=int, default=None)
@_TRIGGERED_BY_OPTION
def ingest_aemo_nem_cmd(lookback_minutes: int | None, triggered_by: str) -> None:
    _run_ingest(
        "aemo-nem", triggered_by=triggered_by, lookback_minutes=lookback_minutes
    )


@ingest.command("aemo-wem")
@click.option("--lookback-minutes", type=int, default=None)
@_TRIGGERED_BY_OPTION
def ingest_aemo_wem_cmd(lookback_minutes: int | None, triggered_by: str) -> None:
    _run_ingest(
        "aemo-wem", triggered_by=triggered_by, lookback_minutes=lookback_minutes
    )


@ingest.command("bom")
@click.option("--lookback-minutes", type=int, default=None)
@_TRIGGERED_BY_OPTION
def ingest_bom_cmd(lookback_minutes: int | None, triggered_by: str) -> None:
    _run_ingest("bom", triggered_by=triggered_by, lookback_minutes=lookback_minutes)


@ingest.command("holidays")
@click.option("--year", type=int, default=None)
@_TRIGGERED_BY_OPTION
def ingest_holidays_cmd(year: int | None, triggered_by: str) -> None:
    _run_ingest("holidays", triggered_by=triggered_by, year=year)


# ── backfill ─────────────────────────────────────────────────────────────


@main.command()
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
    "--duckdb-only",
    is_flag=True,
    default=False,
    help=(
        "Stage every fetched row into the local shared DuckDB staging "
        "file only -- no R2 upload, no RabbitMQ landed-event publish, so "
        "the real Neon-backed raw.* tables are never touched. Also has "
        "no 90-day range cap, unlike POST /v1/data-sources/{id}/backfill "
        "(that cap only exists in the HTTP layer's Redis-lock TTL math, "
        "not in this function)."
    ),
)
def backfill(
    from_: datetime,
    to_: datetime,
    sources: tuple[str, ...],
    lookback_minutes: int,
    duckdb_only: bool,
) -> None:
    """Backfill missing days for one or more ingestion sources (same path
    `POST /v1/data-sources/{id}/backfill` uses). No `--skip-dbt` flag,
    unlike data-pipeline's identical script — this service never runs
    dbt at all."""
    start: date = from_.date()
    end: date = to_.date()
    if start > end:
        raise click.UsageError(f"--from ({start}) must not be after --to ({end})")

    selected = sources or BACKFILLABLE_SOURCES

    results = asyncio.run(
        run_backfill_range(selected, start, end, lookback_minutes, duckdb_only=duckdb_only)
    )
    for (source, day), outcome in results.items():
        click.echo(f"{day} {source}: {outcome}")

    failures = [key for key, outcome in results.items() if outcome.startswith("failed")]
    if failures:
        raise SystemExit(1)


# ── retention ────────────────────────────────────────────────────────────


@main.command("prune-staging")
@click.option(
    "--days",
    type=int,
    default=None,
    help="Override retention.DEFAULT_RETENTION_DAYS (30).",
)
def prune_staging(days: int | None) -> None:
    """Delete local DuckDB rows for runs already durably synced into
    Postgres (`meta._ingest_log.status='success'`) and older than
    `--days` — the shared `landed.duckdb` file's retention policy
    (`services/ingestion/TODO.md`'s Storage section). Manually/cron
    triggered, not on a Celery Beat schedule."""
    from app.service.pipeline.retention import (
        DEFAULT_RETENTION_DAYS,
        prune_synced_history,
    )

    pruned = asyncio.run(prune_synced_history(days or DEFAULT_RETENTION_DAYS))
    if not pruned:
        click.echo("Nothing eligible to prune.")
        return
    for source, rows in sorted(pruned.items()):
        click.echo(f"{source}: {rows} rows pruned")


@main.command("merge-staging")
@click.argument("source", type=click.Choice(list(SOURCES.keys())))
@click.option(
    "--from",
    "from_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a separate staging .duckdb file to merge in.",
)
def merge_staging(source: str, from_path: str) -> None:
    """Merge SOURCE's rows from a separate staging file into the
    canonical shared staging file. For a parallel per-source backfill
    that ran with its own `DUCKDB_STAGING_DIR` to avoid DuckDB's
    single-writer lock on the canonical file -- run this afterward, once
    per source, to reconcile that scratch file back in so `prune-staging`/
    `train-anomaly-model` (which both read the canonical file only) can
    see the full history. Pure local copy, no re-fetch."""
    from app.service.pipeline.duckdb_staging import merge_staging_file

    entry = SOURCES[source]
    rows = merge_staging_file(Path(from_path), entry.table)
    click.echo(f"{source}: {rows} rows merged into the canonical staging file")


# ── ml anomaly model training ───────────────────────────────────────────


@main.command("train-anomaly-model")
@click.argument("source", type=click.Choice(sorted(SOURCES.keys())))
def train_anomaly_model(source: str) -> None:
    """Fit a fresh isolation-forest anomaly model for `source` against
    its accumulated history in the shared DuckDB staging file, and
    upload the artifact to object storage (R2/local MinIO fallback).
    Manually/cron triggered, not on a Celery Beat schedule (`pipeline.
    ml_anomaly`'s own module docstring). A no-op (exit 0, a message, not
    an error) if there isn't enough real history yet."""
    from app.service.pipeline.ml_anomaly import train_and_publish

    entry = SOURCES[source]
    summary = asyncio.run(train_and_publish(entry.source, entry.table))
    if summary is None:
        click.echo(
            f"{source}: not enough history yet to train a model (need at "
            "least ml_anomaly.MIN_TRAINING_ROWS rows) -- skipped."
        )
        return
    click.echo(
        f"{source}: trained on {summary['rows_trained']} rows, "
        f"columns={summary['columns']}, uploaded to {summary['object_storage_key']}"
    )


# ── worker / beat (Celery scheduled dispatch) ────────────────────────────


@main.command(context_settings={"ignore_unknown_options": True})
@click.argument("celery_args", nargs=-1, type=click.UNPROCESSED)
def worker(celery_args: tuple[str, ...]) -> None:
    """Run the Celery worker that executes scheduled ingestion tasks
    (`app.celery_app`'s `beat_schedule` is what actually enqueues them —
    run `beat` alongside this, or nothing gets dispatched on a
    schedule). Equivalent to `celery -A app.celery_app worker`; extra
    args (e.g. `--loglevel=info`, `--concurrency=2`) pass straight
    through."""
    from app.celery_app import celery_app

    celery_app.start(["worker", *celery_args])


@main.command(context_settings={"ignore_unknown_options": True})
@click.argument("celery_args", nargs=-1, type=click.UNPROCESSED)
def beat(celery_args: tuple[str, ...]) -> None:
    """Run the Celery Beat scheduler -- fires each `beat_schedule` entry
    in `app.celery_app` on its real per-source cadence (`oe` every 5
    min, `aemo-nem`/`aemo-wem` every 15, `bom` every 30, `holidays`
    annually), enqueuing a task for a `worker` process to pick up.
    Equivalent to `celery -A app.celery_app beat`."""
    from app.celery_app import celery_app

    celery_app.start(["beat", *celery_args])


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
    """Run the FastAPI app with uvicorn (equivalent to `uvicorn app.main:app`).

    Port resolution order: explicit `--port` > the platform-standard
    `PORT` env var (Railway, Heroku, and most other PaaS targets inject
    this and expect the process to bind it -- confirmed real gap, this
    command never read it before) > `Settings.api_port` (8003, this
    repo's own docker-compose default, used when nothing else is set).
    """
    import os

    import uvicorn

    settings = get_settings()
    resolved_port = port or (int(os.environ["PORT"]) if os.environ.get("PORT") else None) or settings.api_port
    uvicorn.run("app.main:app", host=host, port=resolved_port, reload=reload)


if __name__ == "__main__":
    main()
