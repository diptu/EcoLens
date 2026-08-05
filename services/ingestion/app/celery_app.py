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

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

_settings = get_settings()

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
}
