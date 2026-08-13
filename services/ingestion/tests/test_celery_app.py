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

import asyncio

from celery.schedules import crontab

from app import celery_app as celery_app_module
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
    assert (
        "app.service.pipeline.tasks.celery_tasks.train_anomaly_model_task"
        in celery_app.tasks
    )
    assert (
        "app.service.pipeline.tasks.celery_tasks.train_all_anomaly_models_task"
        in celery_app.tasks
    )


class TestBeatSchedule:
    """One unified 30-minute entry for all 5 sources (2026-08-05 —
    replaced the earlier per-source-cadence design: `oe` every 5 min,
    `aemo-nem`/`aemo-wem` every 15, `bom` every 30, `holidays`
    annually). See `app.celery_app`'s own module comment for the
    tradeoff this accepts (reduced freshness for the higher-frequency
    sources) in exchange for one simple schedule."""

    def test_has_exactly_two_entries(self):
        assert set(celery_app.conf.beat_schedule) == {
            "ingest-all-sources",
            "retrain-all-anomaly-models",
        }

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


class TestRetrainAnomalyModelsBeatSchedule:
    """Weekly retraining entry, added 2026-08-07 — `TODO.md` §2's own
    "still an open decision" resolved: Sunday 02:00 UTC, a deliberate
    default (see `app.celery_app`'s own comment for why), not something
    derived from real observed retraining-cadence needs yet."""

    def test_entry_calls_the_retrain_fan_out_task(self):
        entry = celery_app.conf.beat_schedule["retrain-all-anomaly-models"]
        assert (
            entry["task"]
            == "app.service.pipeline.tasks.celery_tasks.train_all_anomaly_models_task"
        )

    def test_entry_runs_weekly_sunday_2am_utc(self):
        entry = celery_app.conf.beat_schedule["retrain-all-anomaly-models"]
        assert entry["schedule"] == crontab(minute=0, hour=2, day_of_week=0)

    def test_entry_takes_no_kwargs(self):
        # `train_all_anomaly_models_task` takes no arguments -- it fans
        # out to every `backfill.BACKFILLABLE_SOURCES` key itself, same
        # shape as `ingest_all_sources_task`.
        entry = celery_app.conf.beat_schedule["retrain-all-anomaly-models"]
        assert entry.get("kwargs") in (None, {})


class TestRunAsync:
    """`run_async` (2026-08-07) -- the persistent-event-loop-per-worker-
    process fix for a real, live-confirmed bug: `asyncio.run(...)` per
    task creates and destroys its own event loop every call, which is
    fundamentally incompatible with the several process-lifetime-cached
    async clients `run_source`'s call graph touches (Postgres, Redis,
    RabbitMQ all hit `RuntimeError: Event loop is closed` in turn before
    this was fixed at the root instead of patched per-client)."""

    def test_falls_back_to_a_fresh_asyncio_run_with_no_worker_loop(self):
        # The default state outside a real Celery worker process --
        # `worker_process_init` never fired (this test process isn't
        # one), so `_worker_loop` is `None`. Must still work, same as
        # calling `asyncio.run()` directly used to.
        assert celery_app_module._worker_loop is None

        async def coro():
            return 42

        assert celery_app_module.run_async(coro()) == 42

    def test_uses_the_persistent_loop_when_one_is_set(self):
        loop = asyncio.new_event_loop()
        celery_app_module._worker_loop = loop
        try:

            async def coro():
                return asyncio.get_running_loop()

            result_loop = celery_app_module.run_async(coro())

            assert result_loop is loop
        finally:
            celery_app_module._worker_loop = None
            loop.close()

    def test_the_same_loop_is_reused_across_multiple_calls(self):
        """The whole point -- a resource created on the first call must
        still be valid (same loop) on a later call, unlike the old
        `asyncio.run()`-per-call behavior where each call got a fresh,
        then-destroyed loop."""
        loop = asyncio.new_event_loop()
        celery_app_module._worker_loop = loop
        try:

            async def coro():
                return asyncio.get_running_loop()

            first = celery_app_module.run_async(coro())
            second = celery_app_module.run_async(coro())

            assert first is second is loop
        finally:
            celery_app_module._worker_loop = None
            loop.close()

    def test_does_not_use_a_closed_leftover_loop(self):
        loop = asyncio.new_event_loop()
        loop.close()
        celery_app_module._worker_loop = loop
        try:

            async def coro():
                return "fresh"

            # Should fall back to a genuinely fresh asyncio.run(), not
            # try to run on the closed one.
            assert celery_app_module.run_async(coro()) == "fresh"
        finally:
            celery_app_module._worker_loop = None


class TestWorkerProcessLifecycleSignals:
    def test_init_creates_and_sets_a_new_event_loop(self):
        celery_app_module._worker_loop = None
        try:
            celery_app_module._init_worker_event_loop()

            assert celery_app_module._worker_loop is not None
            assert not celery_app_module._worker_loop.is_closed()
        finally:
            if celery_app_module._worker_loop is not None:
                celery_app_module._worker_loop.close()
            celery_app_module._worker_loop = None

    def test_shutdown_closes_the_loop_and_disposes_shared_clients(self, monkeypatch):
        from app.db import redis as redis_module
        from app.db import session as session_module

        disposed = {"db": False, "redis": False}

        async def fake_dispose_db():
            disposed["db"] = True

        async def fake_close_redis():
            disposed["redis"] = True

        monkeypatch.setattr(session_module, "dispose", fake_dispose_db)
        monkeypatch.setattr(redis_module, "close_redis", fake_close_redis)

        celery_app_module._init_worker_event_loop()
        loop = celery_app_module._worker_loop
        assert loop is not None

        celery_app_module._close_worker_event_loop()

        assert disposed == {"db": True, "redis": True}
        assert loop.is_closed()
        assert celery_app_module._worker_loop is None

    def test_shutdown_is_a_noop_when_no_loop_was_ever_created(self):
        celery_app_module._worker_loop = None

        celery_app_module._close_worker_event_loop()  # should not raise

        assert celery_app_module._worker_loop is None
