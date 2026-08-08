"""Celery app + Beat schedule for retention (root `TODO.md`'s "Vacuum
Database should run cronjob using celery to clear older data defined in
.env file").

Before this, `prune`/`export-and-prune`/`vacuum` (`cli.py`) were real,
tested commands with no scheduler at all — this service's own module
docstring called that out explicitly ("this service doesn't schedule
itself, an operator/cron calls in", same as `services/ingestion`'s
`prune-staging` before its own Celery cutover). Mirrors that service's
`app/celery_app.py` structure directly (broker/worker-loop/beat-schedule
shape) rather than inventing a new pattern for one more service.

Broker is the same RabbitMQ instance this service already connects to
(`Settings.rabbitmq_url`, `consume`'s own landed-events queue) — no new
infra dependency. No result backend configured (`backend` left unset) —
same reasoning `services/ingestion`'s app gives: nothing polls task
results, `meta._dbt_build_log`-style audit trails (here: `export_and_
prune`/`vacuum_analyze_raw_tables`'s own return values, logged) are the
real record, not Celery's result store. Unlike ingestion, this service
has no Redis dependency at all (`services/waerehouse/README.md`'s own
health-check note — no circuit-breaker/rate-limit state to keep), so
this app doesn't add one just to satisfy a result backend nothing reads.

Run a worker: `uv run celery -A app.celery_app worker --loglevel=info`
(or `ecolens-warehouse worker`). Run the scheduler: `uv run celery -A
app.celery_app beat --loglevel=info` (or `ecolens-warehouse beat`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init, worker_process_shutdown

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_settings = get_settings()

_T = TypeVar("_T")

# Same one-event-loop-per-forked-worker-process fix `services/ingestion/
# app/celery_app.py` already made (its own module docstring has the full
# incident writeup) -- this service's cached async clients (the Postgres
# engine, the RabbitMQ connection `consume` also uses) are real process-
# lifetime singletons, not safe to recreate every task via a fresh
# `asyncio.run()`.
_worker_loop: asyncio.AbstractEventLoop | None = None


@worker_process_init.connect
def _init_worker_event_loop(**_kwargs: object) -> None:
    global _worker_loop
    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)


@worker_process_shutdown.connect
def _close_worker_event_loop(**_kwargs: object) -> None:
    global _worker_loop
    if _worker_loop is not None and not _worker_loop.is_closed():
        from app.db.session import dispose as dispose_db_engine

        try:
            _worker_loop.run_until_complete(dispose_db_engine())
        finally:
            _worker_loop.close()
    _worker_loop = None


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Runs `coro` on this worker process's one persistent event loop
    instead of a fresh one per task. Falls back to a genuinely fresh
    `asyncio.run()` outside a Celery worker process (tests, direct CLI
    invocation) -- identical contract to ingestion's own `run_async`."""
    if _worker_loop is None or _worker_loop.is_closed():
        return asyncio.run(coro)
    return _worker_loop.run_until_complete(coro)


celery_app = Celery(
    "ecolens_warehouse",
    broker=_settings.rabbitmq_url,
    include=["app.tasks.retention_tasks", "app.tasks.marts_archive_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Daily, 03:00 UTC -- a real low-traffic slot (after `ingest-all-sources`
# and the anomaly-retrain schedule's own off-peak choices in
# `services/ingestion`, before any real business-hours dashboard usage
# this platform's users would hit). `export-and-prune` (not the bare
# `prune`) is the scheduled default -- the safe ordering `cli.py`'s own
# `export_and_prune_cmd` docstring recommends (README Phase 3), so
# nothing gets deleted from Postgres without a durable R2 copy existing
# first. `vacuum` runs right after, in the same task, only if pruning
# actually removed rows -- reclaiming disk space is the whole point of
# running this on a schedule at all (README Phase 3's free-tier-size
# motivation), and running it unconditionally on a no-op day wastes a
# real (if small) amount of Postgres I/O for zero benefit.
celery_app.conf.beat_schedule = {
    "export-and-prune-and-vacuum": {
        "task": "app.tasks.retention_tasks.export_and_prune_and_vacuum_task",
        "schedule": crontab(minute=0, hour=3),
    },
    # 03:30 UTC -- 30 minutes after the raw retention job above, same
    # off-peak reasoning, offset so the two don't compete for the
    # primary database's connection pool at the same moment. No-ops
    # cleanly (real, logged "skipped" status) if RAW_MARTS_DATABASE_URL
    # isn't configured -- root TODO.md's "save raw and raw.marts in
    # seperate database" item.
    "archive-and-prune-marts": {
        "task": "app.tasks.marts_archive_tasks.archive_and_prune_marts_task",
        "schedule": crontab(minute=30, hour=3),
    },
}
