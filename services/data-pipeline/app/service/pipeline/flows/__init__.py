"""Prefect orchestration (`README.md` § Orchestration: "PyTorch trains ->
MLflow tracks/registers -> model promoted via CI -> served", the
`daily-demand` flow example; `TODO.md`'s Forecasting section item 6).

**Scope note**: this is real, importable, runnable `@flow`/`@task`-
decorated code — it actually executes if you call `daily_demand()` or run
`prefect flow-run`/`uv run --package data-pipeline python -m
app.service.pipeline.flows` — but it is *not* wired into a deployed Prefect
schedule/work-pool. `docker-compose.yml`'s `prefect` worker container has
nothing to pick up yet (`infra/docker/worker.Dockerfile`, the image that
container needs, doesn't exist). `TODO.md` previously tracked "zero
`@flow`-decorated code exists anywhere" — this closes that specific gap;
turning it into a scheduled deployment is separate, further work.

**Departure from `README.md`'s pseudocode, and why**: the README example
calls `ingest_aemo_nem()` then `sync_duckdb_to_postgres(raw)`
synchronously, as if warehousing happens inline with ingestion. It
doesn't, by design (`overview.md` §2) — `run_source()` stages to DuckDB
and publishes a RabbitMQ event; a *separate*, independently-scheduled
consumer (`ecolens-pipeline worker` / the `warehouse-sync` docker-compose
service) does the actual Postgres `raw.*` load, on its own schedule, not
synchronously with the ingest call. Running `dbt_build` immediately after
`run_source()` returns would race that consumer — dbt could build against
stale, not-yet-synced data. This flow closes that gap for real:
`wait_for_sync` polls `meta._ingest_log` for each run to reach a terminal
state before `dbt_build_task` runs — something README's simplified
example doesn't need to account for but a real deployment does.

**Event-Driven Pipeline Trigger** (`TODO.md`'s section of that name,
item 1 "Event Publisher"): once `dbt_build_task` actually succeeds, this
flow also publishes a training-trigger event to RabbitMQ
(`publish_training_trigger`) — the "dbt post-execution hook" that
checklist item asks for, adapted to this repo's real orchestration layer
(a Prefect task-completion signal, not literal Airflow, per that item's
own note). This is deliberately independent of `training_due`/
`train_and_register_task` below: those still gate a full from-scratch
retrain on staleness, same as before this pass; the training-trigger
event instead reacts to *every* successful build and is consumed by
`app.service.training_worker` (`ecolens-pipeline train-worker`) to run a
much lighter, warm-started incremental fine-tune (`ml.incremental`) —
two different cadences for two different kinds of update, not one
replacing the other.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

from prefect import flow, task
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_session
from app.service.dbt_runner import run_dbt
from app.service.ml.train import train_and_register
from app.service.mlops.registry import get_version_in_stage
from app.db.rabbitmq import publish_training_trigger_event
from app.core.logging import get_logger
from app.service.pipeline.tasks.registry import SOURCES, run_source

log = get_logger(__name__)

# The 4 sources `ml/data.py`'s `load_training_data` mart
# (`raw_marts.fct_energy_demand`) actually depends on -- `holidays` isn't
# included since it refreshes once a year (`registry.SOURCES["holidays"]`),
# not something worth re-ingesting on a daily training cadence.
DEMAND_TRAINING_SOURCES: tuple[str, ...] = ("aemo-nem", "aemo-wem", "bom", "oe")

_TERMINAL_STATUSES = ("success", "sync_failed", "failed")


@task(name="ingest-source", retries=1)
async def ingest_source(registry_key: str) -> str:
    """Runs the ingest, returns the `meta._ingest_log` run id it wrote.
    `run_source()` itself only returns a row count (see its docstring),
    not the run id, so this re-queries the most-recent row for the
    source right after `run_source` returns rather than threading a run
    id back through `standard_run`'s return type just for this."""
    await run_source(registry_key, triggered_by="schedule")
    source = SOURCES[registry_key].source
    async with get_session() as db:
        row = (
            await db.execute(
                text(
                    "SELECT id FROM meta._ingest_log WHERE source = :source "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"source": source},
            )
        ).first()
    return str(row[0]) if row is not None else ""


@task(name="wait-for-sync", retries=0)
async def wait_for_sync(
    run_id: str, timeout_seconds: int = 300, poll_seconds: int = 5
) -> str:
    """Polls `meta._ingest_log.status` for `run_id` until it reaches a
    terminal state (`success`/`sync_failed`/`failed`) or `timeout_seconds`
    elapses (returning `"timeout"` — logged as a warning, not raised, so
    one slow/stuck sync doesn't take the whole flow down; `dbt_build`
    running against a still-`staged` source is a data-freshness problem
    the next day's run will self-correct, not a reason to fail this one).
    """
    if not run_id:
        return "unknown"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        async with get_session() as db:
            row = (
                await db.execute(
                    text("SELECT status FROM meta._ingest_log WHERE id = :id"),
                    {"id": run_id},
                )
            ).first()
        status = row[0] if row is not None else "unknown"
        if status in _TERMINAL_STATUSES:
            return status
        await asyncio.sleep(poll_seconds)
    log.warning(
        "flows.wait_for_sync_timeout", run_id=run_id, timeout_seconds=timeout_seconds
    )
    return "timeout"


@task(name="dbt-build")
def dbt_build_task(target: str = "prod") -> int:
    settings = get_settings()
    return run_dbt("build", settings.dbt_project_dir, target, [])


@task(name="publish-training-trigger")
async def publish_training_trigger(regions: list[str], window_hours: int) -> None:
    """`TODO.md` item 1's "Event Publisher": fires once `dbt_build_task`
    (the "dbt post-execution hook", adapted to a Prefect task-completion
    signal per that item's own note) has actually succeeded. The payload
    is item 1's "batch metadata": the dataset the build refreshed, the
    timestamp window `app.service.training_worker`'s incremental trainer
    should query (`Settings.incremental_train_window_hours` back from
    now), and a real anomaly-summary flag count from `meta.anomalies`
    over that same window — not a placeholder field.
    """
    window_until = datetime.now(UTC)
    window_since = window_until - timedelta(hours=window_hours)
    async with get_session() as db:
        row = (
            await db.execute(
                text("SELECT count(*) FROM meta.anomalies WHERE detected_at >= :since"),
                {"since": window_since},
            )
        ).first()
    anomalies_flagged = int(row[0]) if row is not None else 0

    payload = {
        "event": "warehouse.transform.completed",
        "occurred_at": window_until.isoformat(),
        "dataset": "raw_marts.fct_energy_demand",
        "regions": regions,
        "window_since": window_since.isoformat(),
        "window_until": window_until.isoformat(),
        "anomalies_flagged": anomalies_flagged,
    }
    await publish_training_trigger_event(payload)
    log.info(
        "flows.training_trigger_published",
        regions=regions,
        window_since=payload["window_since"],
        anomalies_flagged=anomalies_flagged,
    )


@task(name="training-due")
def training_due(model_name: str, min_age_days: int = 7) -> bool:
    """`True` if there's no `Production` model version yet, or the
    current one is older than `min_age_days` — a real, simple staleness
    check (`README.md`'s pseudocode leaves `training_due()` as an
    unexplained placeholder)."""
    version = get_version_in_stage(model_name, "Production")
    if version is None:
        return True
    created_at = datetime.fromtimestamp(version.creation_timestamp / 1000, tz=UTC)
    return (datetime.now(UTC) - created_at) > timedelta(days=min_age_days)


@task(name="train-and-register")
async def train_and_register_task(model_name: str, regions: list[str]) -> str:
    result = await train_and_register(model_name, regions, register=True)
    return result.run_id


@flow(name="daily-demand")
async def daily_demand(
    regions: list[str] | None = None, target: str | None = None
) -> None:
    settings = get_settings()
    resolved_regions = regions or settings.model_default_regions
    resolved_target = target or settings.dbt_target

    run_ids = [await ingest_source(key) for key in DEMAND_TRAINING_SOURCES]
    for run_id in run_ids:
        await wait_for_sync(run_id)

    dbt_exit_code = dbt_build_task(target=resolved_target)
    if dbt_exit_code == 0:
        await publish_training_trigger(
            resolved_regions, settings.incremental_train_window_hours
        )
    else:
        log.warning(
            "flows.dbt_build_failed_skipping_training_trigger", exit_code=dbt_exit_code
        )

    model_name = settings.mlflow_registry_model_name
    if training_due(model_name):
        run_id = await train_and_register_task(model_name, resolved_regions)
        log.info("flows.trained", model_name=model_name, run_id=run_id)
    else:
        log.info("flows.training_not_due", model_name=model_name)


if __name__ == "__main__":
    asyncio.run(daily_demand())
