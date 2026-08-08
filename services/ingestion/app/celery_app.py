"""Celery app + Beat schedule (`services/ingestion/TODO.md`'s "Ingestion
Pipeline Mechanism" — "scheduled cron triggers dispatch asynchronous
background tasks managed by Celery").

Broker is the same RabbitMQ instance `db.rabbitmq.publish_landed_event`
already publishes landed events to (`Settings.rabbitmq_url`) — reuses
existing infrastructure rather than adding a new one just for task
dispatch. Result backend is the same Redis instance the circuit breaker
already uses (`Settings.redis_url`) — task results aren't the point here
(nothing polls them; `meta._ingest_log` is still the real audit trail,
via `pipeline.tasks._common.standard_run`, unchanged), but Celery wants
*some* backend configured to track task state at all.

The actual ingestion logic is untouched — `app.service.pipeline.tasks.
celery_tasks.ingest_source_task`/`ingest_all_sources_task` are thin
wrappers around `registry.run_source`, the same single call site the CLI
and HTTP API already go through. Celery Beat is one more trigger source
alongside those, not a replacement for `run_source` itself.

Run a worker: `uv run celery -A app.celery_app worker --loglevel=info`
(or `ecolens-ingestion worker`). Run the scheduler: `uv run celery -A
app.celery_app beat --loglevel=info` (or `ecolens-ingestion beat`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init, worker_process_shutdown

from app.core.config import get_settings
from app.core.tracing import configure_tracing

_settings = get_settings()

_T = TypeVar("_T")

# **2026-08-07 — one persistent event loop per forked worker process,
# not a fresh one per task.** Real, live-confirmed bug, found across
# three separate rounds: `celery_tasks.py` used to call `asyncio.run(
# ...)` per task, which creates *and fully destroys* its own event loop
# every time. Every cached async client this service's ingest path
# touches -- the Postgres engine (`app.db.session.get_engine`), the
# Redis client (`app.db.redis.get_redis`), the RabbitMQ connection
# (`app.db.rabbitmq.get_rabbitmq_connection`) -- is a real, process-
# lifetime singleton (either `@lru_cache`'d or a module-level global)
# that's meant to survive across many calls. Disposing each one
# individually at the end of every task (tried first, for Postgres and
# Redis) turned into whack-a-mole -- RabbitMQ's own module-level
# connection hit the identical failure next, and there was no reason to
# believe it'd be the last one. The actual root cause is the fresh-
# loop-per-task model itself: *any* async resource meant to be reused
# across tasks is fundamentally incompatible with a new event loop being
# created and destroyed around every single call. Fixed at the root
# instead: one event loop per forked worker child, created once via
# `worker_process_init` and reused for every task that process ever
# runs, closed only at real process shutdown (`worker_process_shutdown`)
# -- the same lifetime every one of those cached clients already assumes
# it has. `run_async` below is what `celery_tasks.py` now calls instead
# of `asyncio.run(...)` directly.
_worker_loop: asyncio.AbstractEventLoop | None = None


@worker_process_init.connect
def _init_worker_event_loop(**_kwargs: object) -> None:
    global _worker_loop
    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)
    # Configured fresh in *this* forked child, never inherited from the
    # parent `worker` process -- see `cli.py`'s `main()` group callback
    # for why tracing is deliberately never configured before Celery's
    # prefork pool forks (a live gRPC exporter channel/thread doesn't
    # survive `fork()` safely).
    configure_tracing()


@worker_process_shutdown.connect
def _close_worker_event_loop(**_kwargs: object) -> None:
    global _worker_loop
    if _worker_loop is not None and not _worker_loop.is_closed():
        # Best-effort disposal of the same cached clients `celery_tasks`
        # used to dispose per-task -- now done once, at real process end,
        # under the same loop that's about to close, not after every task.
        from app.db.redis import close_redis
        from app.db.session import dispose as dispose_db_engine

        async def _cleanup() -> None:
            await dispose_db_engine()
            await close_redis()

        try:
            _worker_loop.run_until_complete(_cleanup())
        finally:
            _worker_loop.close()
    _worker_loop = None


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """`celery_tasks.py`'s replacement for `asyncio.run(coro)` -- runs
    `coro` on this worker process's one persistent event loop
    (`_worker_loop`, created by `worker_process_init` above) instead of
    a fresh one that gets destroyed when `coro` finishes. Falls back to
    a genuinely fresh `asyncio.run()` if called outside a Celery worker
    process (e.g. directly in a test or script, where `worker_process_
    init` never fired) -- same behavior as before this fix in that
    context, since there's no multi-task process lifetime to preserve
    anything across."""
    if _worker_loop is None or _worker_loop.is_closed():
        return asyncio.run(coro)
    return _worker_loop.run_until_complete(coro)


celery_app = Celery(
    "ecolens_ingestion",
    broker=_settings.rabbitmq_url,
    backend=_settings.redis_url,
    include=["app.service.pipeline.tasks.celery_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # `meta._ingest_log`/`already_succeeded` (`pipeline.backfill`'s own
    # idempotency check, also true of a plain scheduled run — a source
    # already `running`/`staged` gets a 409-equivalent skip inside
    # `standard_run` itself) is what actually prevents duplicate work,
    # not Celery retry/late-ack semantics -- keep task results around
    # briefly for operator visibility (`celery -A app.celery_app
    # result <id>`), not as a durability mechanism.
    result_expires=3600,
)

# **2026-08-05 update — one unified 30-minute schedule for all 5
# sources, replacing the earlier per-source-cadence design** (`oe`
# every 5 min, `aemo-nem`/`aemo-wem` every 15, `bom` every 30,
# `holidays` annually) per an explicit request. Simpler — one Beat
# entry instead of five — at a real, known cost: `oe`'s actual 5-minute
# update frequency is no longer matched, so data freshness for the
# higher-frequency sources drops accordingly. `ingest_all_sources_task`
# (`pipeline.tasks.celery_tasks`) still dispatches each source as its
# own independent child task (`celery.group`), not a single sequential
# loop — one slow/hung source still can't hold up the others, same
# "resilient, decoupled" property the per-source design also had.
celery_app.conf.beat_schedule = {
    "ingest-all-sources": {
        "task": "app.service.pipeline.tasks.celery_tasks.ingest_all_sources_task",
        "schedule": crontab(minute="*/30"),
        "kwargs": {"triggered_by": "schedule"},
    },
    # **2026-08-07 — anomaly retraining automation.** `TODO.md` §2 left
    # this deliberately open ("retraining trigger: manual/CLI-triggered,
    # *not* a Celery Beat schedule... wiring a periodic Beat entry later
    # ... is a small, additive follow-up"). Weekly (Sunday 02:00 UTC, a
    # real low-traffic slot for every source here — none of NEM/WEM/OE/
    # BOM's polling cadences depend on wall-clock day-of-week) is a
    # reasonable default, not a carefully-tuned cadence — the accumulated
    # history each source's model trains on changes slowly enough that
    # daily would be wasted compute and monthly risks drifting behind a
    # real seasonal shift. Change this single crontab if that default
    # turns out wrong; `train_all_anomaly_models_task` itself doesn't
    # need to change either way.
    "retrain-all-anomaly-models": {
        "task": (
            "app.service.pipeline.tasks.celery_tasks.train_all_anomaly_models_task"
        ),
        "schedule": crontab(minute=0, hour=2, day_of_week=0),
    },
}
