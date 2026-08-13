"""Celery task wrappers around `registry.run_source` — the scheduled-
dispatch half of `services/ingestion/TODO.md`'s "Ingestion Pipeline
Mechanism" (`app.celery_app`'s `beat_schedule` is what actually invokes
`ingest_all_sources_task`, on a single unified cadence).

Deliberately thin: `run_source` is still the one call site the CLI,
the HTTP API, and Celery Beat all go through — this module only bridges
Celery's synchronous task-execution model to `run_source`'s async one.
No retry/backoff here — a failed run is already recorded in `meta.
_ingest_log` (`status="failed"`, via `_common.standard_run` itself) and
the next Beat tick picks the source back up on its own regular cadence;
a Celery-level retry on top would just be a second, uncoordinated retry
mechanism racing the circuit breaker's own half-open/backoff logic.

**2026-08-07 — uses `app.celery_app.run_async`, not `asyncio.run(...)`
directly.** See that function's own module-level docstring in
`celery_app.py` for the real, live-confirmed bug this fixes (a fresh
event loop per task is fundamentally incompatible with the several
process-lifetime-cached async clients `run_source`'s call graph touches
— Postgres, Redis, RabbitMQ all hit `RuntimeError: Event loop is
closed` in turn before this was fixed at the root instead of patched
per-client).
"""

from __future__ import annotations

from celery import group

from app.celery_app import celery_app, run_async
from app.core.logging import configure_logging, get_logger
from app.service.pipeline.backfill import BACKFILLABLE_SOURCES
from app.service.pipeline.tasks.registry import SOURCES, run_source

log = get_logger(__name__)


@celery_app.task(name="app.service.pipeline.tasks.celery_tasks.ingest_source_task")
def ingest_source_task(
    key: str, triggered_by: str = "schedule", **kwargs: object
) -> int:
    """Runs one ingest source to completion, synchronously from Celery's
    point of view. Returns rows staged (see `registry.run_source`'s own
    docstring) — not awaited by anything today (Beat fires-and-forgets),
    but a real return value all the same, visible via `celery -A
    app.celery_app result <task-id>` for the `result_expires` window.
    """
    configure_logging()
    log.info("celery_tasks.ingest_started", source=key, triggered_by=triggered_by)
    try:
        rows = run_async(
            run_source(key, triggered_by=triggered_by, **kwargs)  # type: ignore[arg-type]
        )
    except Exception as exc:
        log.error("celery_tasks.ingest_failed", source=key, error=str(exc))
        raise
    log.info("celery_tasks.ingest_finished", source=key, rows_staged=rows)
    return rows


@celery_app.task(name="app.service.pipeline.tasks.celery_tasks.ingest_all_sources_task")
def ingest_all_sources_task(triggered_by: str = "schedule") -> list[str]:
    """Fans out one `ingest_source_task` per `registry.SOURCES` key, in
    parallel (`celery.group`) — the single Beat entry (`app.celery_app`'s
    `beat_schedule`, every 30 minutes, all 5 sources) fires this once,
    which then dispatches 5 independent child tasks rather than fetching
    sources sequentially in one long-running task.

    Independent dispatch matters here specifically because it preserves
    the "one bad source shouldn't hold up the others" property every
    other multi-source path in this service already has (`pipeline.
    backfill.backfill`'s per-day/per-source loop, `_common.standard_run`'s
    per-run circuit breaker) — a single combined task looping over all 5
    sources in-process would make a slow/hung `oe` fetch delay `bom`'s
    fetch behind it for no reason.

    Returns the 5 child tasks' ids (`AsyncResult.id`), not their
    results — `group()` dispatches and returns immediately; each child's
    real outcome still lands in `meta._ingest_log` independently, same
    as it would from a direct `ingest_source_task` call.

    **Known tradeoff, not an oversight**: this replaces the earlier
    per-source-cadence design (`oe` every 5 min, `aemo-nem`/`aemo-wem`
    every 15, `bom` every 30, `holidays` annually) with one uniform
    30-minute cadence for all 5 — simpler, but `oe`'s real 5-minute
    update frequency is no longer matched; data freshness for the
    higher-frequency sources is reduced accordingly. A deliberate,
    requested simplification, not something this module tried to hide.
    """
    job = group(
        ingest_source_task.si(key, triggered_by=triggered_by) for key in SOURCES
    )
    log.info("celery_tasks.dispatching_all_sources", sources=sorted(SOURCES))
    result = job.apply_async()
    return [child.id for child in result.results]


@celery_app.task(
    name="app.service.pipeline.tasks.celery_tasks.train_anomaly_model_task"
)
def train_anomaly_model_task(key: str) -> dict[str, object] | None:
    """Same body as `ecolens-ingestion train-anomaly-model <source>`
    (`app/cli.py`), wrapped as a Celery task so `train_all_anomaly_
    models_task` below can schedule it on Beat instead of relying on an
    operator to run the CLI by hand — `ml_anomaly`'s own module docstring
    left this as "a small, additive follow-up... once real
    retraining-cadence needs are known", not a redesign of anything
    around it. `train_and_publish` returning `None` (not enough real
    history yet, `ml_anomaly.MIN_TRAINING_ROWS`) is logged at `warning`,
    not silently swallowed — the whole point of adding this is to make a
    skipped/failed retrain visible instead of only discoverable by
    noticing a model's `ml_score` never seems to fire.
    """
    from app.service.pipeline.ml_anomaly import train_and_publish

    configure_logging()
    entry = SOURCES[key]
    log.info("celery_tasks.retrain_started", source=key)
    try:
        summary = run_async(train_and_publish(entry.source, entry.table))
    except Exception as exc:
        log.error("celery_tasks.retrain_failed", source=key, error=str(exc))
        raise
    if summary is None:
        log.warning(
            "celery_tasks.retrain_skipped",
            source=key,
            reason="not enough accumulated history yet (below ml_anomaly."
            "MIN_TRAINING_ROWS)",
        )
        return None
    log.info("celery_tasks.retrain_finished", **summary)
    return summary


@celery_app.task(
    name="app.service.pipeline.tasks.celery_tasks.train_all_anomaly_models_task"
)
def train_all_anomaly_models_task() -> list[str]:
    """Weekly Beat entry (`app.celery_app`'s `beat_schedule`) fanning out
    one `train_anomaly_model_task` per backfillable source
    (`pipeline.backfill.BACKFILLABLE_SOURCES` — `holidays` excluded, same
    reason it never gets an anomaly model at all: no numeric columns).
    Same independent-`celery.group` shape as `ingest_all_sources_task`,
    for the same reason: one source's retrain being slow or skipped
    (too little history) shouldn't delay the others.
    """
    job = group(train_anomaly_model_task.si(key) for key in BACKFILLABLE_SOURCES)
    log.info(
        "celery_tasks.dispatching_all_retrains", sources=sorted(BACKFILLABLE_SOURCES)
    )
    result = job.apply_async()
    return [child.id for child in result.results]
