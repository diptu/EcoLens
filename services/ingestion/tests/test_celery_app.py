"""Tests for `app.celery_app` -- the Celery app instance + Beat schedule
that dispatches scheduled ingestion (`services/ingestion/TODO.md`'s
"Ingestion Pipeline Mechanism"). Live worker/broker connectivity is
exercised manually (not in this suite -- would need a real RabbitMQ/
Redis reachable in CI); this file checks the *configuration* is correct
--- the actual real-broker round trip was verified live against local
RabbitMQ + Redis while building this out: a real `ingest_all_sources_
task` dispatched via `.delay()`, picked up by a real worker, which
fanned out into 5 real independent `ingest_source_task` children
(confirmed via the worker's own log -- one `received`/`ingest_started`
pair per source, all 5 real registry keys)."""

from __future__ import annotations

from celery.schedules import crontab

from app.celery_app import celery_app
from app.core.config import get_settings


def test_broker_is_the_configured_rabbitmq_url():
    settings = get_settings()
    assert celery_app.conf.broker_url == settings.rabbitmq_url


def test_result_backend_is_the_configured_redis_url():
    settings = get_settings()
    assert celery_app.conf.result_backend == settings.redis_url


def test_both_tasks_are_registered():
    celery_app.loader.import_default_modules()

    assert (
        "app.service.pipeline.tasks.celery_tasks.ingest_source_task" in celery_app.tasks
    )
    assert (
        "app.service.pipeline.tasks.celery_tasks.ingest_all_sources_task"
        in celery_app.tasks
    )


class TestBeatSchedule:
    """One unified 30-minute entry for all 5 sources (2026-08-05 —
    replaced the earlier per-source-cadence design: `oe` every 5 min,
    `aemo-nem`/`aemo-wem` every 15, `bom` every 30, `holidays`
    annually). See `app.celery_app`'s own module comment for the
    tradeoff this accepts (reduced freshness for the higher-frequency
    sources) in exchange for one simple schedule."""

    def test_has_exactly_one_entry(self):
        assert set(celery_app.conf.beat_schedule) == {"ingest-all-sources"}

    def test_entry_calls_the_fan_out_task(self):
        entry = celery_app.conf.beat_schedule["ingest-all-sources"]
        assert (
            entry["task"]
            == "app.service.pipeline.tasks.celery_tasks.ingest_all_sources_task"
        )

    def test_entry_runs_every_30_minutes(self):
        entry = celery_app.conf.beat_schedule["ingest-all-sources"]
        assert entry["schedule"] == crontab(minute="*/30")

    def test_entry_is_triggered_by_schedule(self):
        entry = celery_app.conf.beat_schedule["ingest-all-sources"]
        assert entry["kwargs"] == {"triggered_by": "schedule"}

    def test_entry_takes_no_positional_source_arg(self):
        # Unlike the old per-source entries -- `ingest_all_sources_task`
        # takes no `key`, it fans out to every `registry.SOURCES` key
        # itself.
        entry = celery_app.conf.beat_schedule["ingest-all-sources"]
        assert entry.get("args") in (None, ())
