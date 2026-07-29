"""The internal control surface for the warehouse pipeline -- trigger a
run, poll it, or check the last completed run. A plain `APIRouter` (same
shape as `ingestion.api`/`forecasting.api`'s own routers), meant to be
mounted on data-pipeline's own control API (`ecolens.api.app`).

Uses `JobTracker` (same as `ingestion.api`'s `/historical` endpoints,
not `forecasting.api`'s fire-and-forget `/train`) because a warehouse
run's `RunResult` is a rich per-stage breakdown (rows synced per source,
dbt's own row counts, quality violations, ...) that's worth retrieving
per-invocation, not just "is there a current production model" -- there
can be several runs in flight or recently finished, and a caller (e.g.
an orchestrating cron job deciding whether to alert) wants *this run's*
outcome specifically.

`GET /warehouse/last-run` is the restart-survivable complement: it reads
`MetricsEmitter`'s persisted `warehouse-runs.jsonl` (one JSON line per
run, appended regardless of which process -- this API, the CLI, a cron
job -- triggered it), so "what happened last time" still answers correctly
even after this API process restarts and its in-memory `JobTracker` has
forgotten every job it ever tracked.

Runs in the background: a real run's dbt step alone is a subprocess call
that blocks for the run's whole duration (`DbtRunner.run()` is
synchronous by design, see that module's docstring) -- same accepted
tradeoff `forecasting.api`'s `/train` already makes for `train_model()`'s
CPU-bound loop, not something this endpoint tries to fix on its own.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ecolens.shared.job_tracker import JobTracker
from ecolens.shared.observability.logging import get_logger

from ecolens.warehouse.core.runner_settings import get_warehouse_runner_settings
from ecolens.warehouse.service.event_consumer import STATUS_FILENAME
from ecolens.warehouse.service.orchestrator import WarehouseRunner

log = get_logger(__name__)

router = APIRouter(prefix="/warehouse", tags=["warehouse"])

_jobs = JobTracker()

Mode = Literal["incremental", "full", "validate"]


async def _run_pipeline_job(
    mode: Mode,
    dbt_select: list[str] | None,
    dbt_exclude: list[str] | None,
    skip_aggregates: bool,
    skip_archive: bool,
) -> dict[str, Any]:
    runner = WarehouseRunner(get_warehouse_runner_settings())
    result = await runner.run(
        mode=mode,
        dbt_select=dbt_select,
        dbt_exclude=dbt_exclude,
        skip_aggregates=skip_aggregates,
        skip_archive=skip_archive,
    )
    return result.to_dict()


@router.post("/run")
async def trigger_warehouse_run(
    background_tasks: BackgroundTasks,
    mode: Mode = Query(
        "incremental",
        description=(
            "'incremental' (default; normally triggered automatically by "
            "ecolens.warehouse.service.event_consumer on a RabbitMQ "
            "'data ingested' event, not a schedule): syncs raw.* since "
            "Settings.raw_sync_lookback_days, then `dbt build`. "
            "'full': resyncs every raw row + `dbt build --full-refresh` "
            "(manual/as-needed, not scheduled). 'validate': source-freshness check only, "
            "no sync or dbt run."
        ),
    ),
    select: list[str] | None = Query(
        None, description="dbt --select (e.g. tag:ml_features, +fact_demand_30min)."
    ),
    exclude: list[str] | None = Query(
        None, description="dbt --exclude (e.g. tag:dev)."
    ),
    skip_aggregates: bool = Query(False, description="skip materialized-view refresh."),
    skip_archive: bool = Query(False, description="skip the archive + vacuum stage."),
) -> dict[str, str]:
    """Triggers `WarehouseRunner`'s 7-stage pipeline (source freshness ->
    raw sync -> dbt build -> data quality -> aggregate refresh -> metrics
    -> archive/vacuum) in the background.

    Returns immediately with a `job_id` -- poll
    `GET /warehouse/run/{job_id}` for the full per-stage result. A stale
    DuckDB store (no live ingestion having run recently) fails the very
    first stage (`source_freshness`) by design -- see
    `runner/freshness.py` -- rather than silently building the warehouse
    from data everyone should already distrust.
    """
    job_id = _jobs.start(mode=mode, select=select, exclude=exclude)
    background_tasks.add_task(
        _jobs.run,
        job_id,
        _run_pipeline_job,
        mode,
        select,
        exclude,
        skip_aggregates,
        skip_archive,
    )
    log.info("api.warehouse_run_triggered", job_id=job_id, mode=mode)
    return {"status": "started", "job_id": job_id, "mode": mode}


@router.get("/run/{job_id}")
async def get_warehouse_run_status(job_id: str) -> dict[str, Any]:
    """Poll a `/warehouse/run` trigger's outcome by its `job_id`.

    `status` is `"running"`, `"completed"`, or `"failed"`; `result`
    (only set once `completed`) is the full `RunResult.to_dict()` --
    every stage's name/success/rows_affected/error/metrics, in order.
    `"failed"` here means the job function itself raised (a genuine bug,
    e.g. a settings misconfiguration) -- a stage failing cleanly (stale
    freshness, a dbt test failure) still shows up as `"completed"` with
    `result.success = false` and the failing stage's own `error` set.
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"No such job: {job_id!r} (unknown, or the server restarted since it ran)",
        )
    return {
        **job.meta,
        "job_id": job.job_id,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "result": job.result,
        "error": job.error,
    }


def _read_run_lines(limit: int | None = None) -> list[dict[str, Any]]:
    """Reads `data/log/warehouse-runs.jsonl`, most recent last (or, with
    `limit`, the most recent `limit` lines only) -- one JSON object per
    completed run, appended regardless of which process (this API, the
    CLI, `event_consumer`) triggered it.
    """
    settings = get_warehouse_runner_settings()
    log_file = settings.log_dir / "warehouse-runs.jsonl"
    if not log_file.exists():
        return []
    lines = [line.strip() for line in log_file.open() if line.strip()]
    if limit is not None:
        lines = lines[-limit:]
    return [json.loads(line) for line in lines]


@router.get("/last-run")
async def get_last_warehouse_run() -> dict[str, Any]:
    """The most recently *completed* run, read straight from
    `data/log/warehouse-runs.jsonl` -- survives this API process
    restarting (unlike `/warehouse/run/{job_id}`, which only knows about
    jobs its own in-memory `JobTracker` triggered), and reflects a run
    triggered by the CLI or a cron job just as well as one triggered
    here.
    """
    runs = _read_run_lines(limit=1)
    if not runs:
        raise HTTPException(status_code=404, detail="no warehouse runs recorded yet")
    return runs[0]


@router.get("/runs")
async def get_recent_warehouse_runs(
    limit: int = Query(20, ge=1, le=200, description="Most recent N runs, newest last."),
) -> list[dict[str, Any]]:
    """Recent completed-run history for the dashboard's admin section --
    same source of truth as `/last-run` (`data/log/warehouse-runs.jsonl`),
    just more than the single most recent line. Empty list (not a 404)
    when nothing's recorded yet, since "no history" is a normal state
    for a page rendering a list/chart, not an error.
    """
    return _read_run_lines(limit=limit)


@router.get("/consumer-status")
async def get_consumer_status() -> dict[str, Any]:
    """`ecolens.warehouse.service.event_consumer.WarehouseEventConsumer`'s
    own heartbeat file (`data/log/warehouse_consumer_status.json`) --
    the consumer daemon has no HTTP surface of its own, so this is the
    only way anything (e.g. the dashboard's admin section) can see
    whether it's listening, what it last received, and what its last
    triggered run did.
    """
    settings = get_warehouse_runner_settings()
    status_file = settings.log_dir / STATUS_FILENAME
    if not status_file.exists():
        raise HTTPException(
            status_code=404,
            detail="consumer has never reported status (not running yet?)",
        )
    return json.loads(status_file.read_text())


__all__ = ["router"]
