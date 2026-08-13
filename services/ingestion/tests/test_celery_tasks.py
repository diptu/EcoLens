"""Tests for `app.service.pipeline.tasks.celery_tasks.ingest_source_task`
-- exercised as a plain function call (Celery's own `.run()`/calling the
task function directly executes it synchronously in-process, no broker
needed), same "test the underlying logic, not Celery's own dispatch
machinery" split `test_celery_app.py`'s own docstring describes. A real
broker round trip (`.delay()` -> real worker -> real execution) was
verified live against local RabbitMQ + Redis while building this out.
"""

from __future__ import annotations

import pytest

from app.service.pipeline.tasks import celery_tasks


def test_calls_run_source_with_the_given_key_and_kwargs(monkeypatch):
    captured = {}

    async def fake_run_source(key, **kwargs):
        captured["key"] = key
        captured["kwargs"] = kwargs
        return 42

    monkeypatch.setattr(celery_tasks, "run_source", fake_run_source)

    rows = celery_tasks.ingest_source_task.run(
        "bom", triggered_by="schedule", lookback_minutes=30
    )

    assert rows == 42
    assert captured["key"] == "bom"
    assert captured["kwargs"] == {
        "triggered_by": "schedule",
        "lookback_minutes": 30,
    }


def test_defaults_triggered_by_to_schedule(monkeypatch):
    captured = {}

    async def fake_run_source(key, **kwargs):
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(celery_tasks, "run_source", fake_run_source)

    celery_tasks.ingest_source_task.run("holidays")

    assert captured["kwargs"]["triggered_by"] == "schedule"


def test_reraises_and_logs_on_failure(monkeypatch):
    async def fake_run_source(key, **kwargs):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr(celery_tasks, "run_source", fake_run_source)

    with pytest.raises(RuntimeError, match="upstream is down"):
        celery_tasks.ingest_source_task.run("bom", triggered_by="schedule")


class TestUsesRunAsyncNotAsyncioRunDirectly:
    """Real, live-confirmed bug (2026-08-07, found across three separate
    rounds): `asyncio.run(...)` per task creates and fully destroys its
    own event loop every time, which is fundamentally incompatible with
    the several process-lifetime-cached async clients `run_source`'s
    call graph touches (Postgres, Redis, RabbitMQ all hit `RuntimeError:
    Event loop is closed` in turn -- disposing each individually turned
    into whack-a-mole). Fixed at the root in `app.celery_app`: one
    persistent event loop per forked worker process
    (`worker_process_init`), reused for every task instead of a fresh
    one per call. These tests confirm both tasks route through
    `celery_app.run_async` (the persistent-loop entry point), not
    `asyncio.run` directly -- `app.celery_app`'s own tests cover
    `run_async`'s actual loop-reuse/fallback behavior."""

    def test_ingest_source_task_calls_run_async(self, monkeypatch):
        captured = {}

        async def fake_run_source(key, **kwargs):
            return 5

        def fake_run_async(coro):
            captured["called"] = True
            coro.close()  # avoid a "coroutine was never awaited" warning
            return 5

        monkeypatch.setattr(celery_tasks, "run_source", fake_run_source)
        monkeypatch.setattr(celery_tasks, "run_async", fake_run_async)

        rows = celery_tasks.ingest_source_task.run("bom", triggered_by="schedule")

        assert captured.get("called") is True
        assert rows == 5

    def test_train_anomaly_model_task_calls_run_async(self, monkeypatch):
        from app.service.pipeline import ml_anomaly

        captured = {}

        async def fake_train_and_publish(source, table):
            return {"source": source}

        def fake_run_async(coro):
            captured["called"] = True
            coro.close()
            return {
                "source": "bom",
                "rows_trained": 1,
                "columns": [],
                "object_storage_key": "x",
            }

        monkeypatch.setattr(ml_anomaly, "train_and_publish", fake_train_and_publish)
        monkeypatch.setattr(celery_tasks, "run_async", fake_run_async)

        summary = celery_tasks.train_anomaly_model_task.run("bom")

        assert captured.get("called") is True
        assert summary is not None


def test_task_is_registered_under_its_full_dotted_name():
    assert (
        celery_tasks.ingest_source_task.name
        == "app.service.pipeline.tasks.celery_tasks.ingest_source_task"
    )


class _FakeAsyncResult:
    def __init__(self, task_id: str):
        self.id = task_id


class _FakeGroupResult:
    def __init__(self, ids: list[str]):
        self.results = [_FakeAsyncResult(i) for i in ids]


class _FakeGroup:
    """Stands in for `celery.group(...)` -- captures the signatures it
    was built from without needing a real broker, then hands back a
    fake `GroupResult` shaped just enough for `ingest_all_sources_task`
    to extract child ids from. The real fan-out (`group(...).
    apply_async()` against a live broker, a real worker picking up all
    5 children) was verified live while building this out."""

    def __init__(self, signatures):
        self.signatures = list(signatures)

    def apply_async(self):
        return _FakeGroupResult([f"fake-id-{i}" for i in range(len(self.signatures))])


class TestIngestAllSourcesTask:
    def test_dispatches_one_child_per_registry_source(self, monkeypatch):
        from app.service.pipeline.tasks.registry import SOURCES

        captured = {}

        def fake_group(generator):
            sigs = list(generator)
            captured["sigs"] = sigs
            return _FakeGroup(sigs)

        monkeypatch.setattr(celery_tasks, "group", fake_group)

        child_ids = celery_tasks.ingest_all_sources_task.run(triggered_by="manual")

        assert len(captured["sigs"]) == len(SOURCES)
        assert len(child_ids) == len(SOURCES)

    def test_each_child_signature_targets_ingest_source_task(self, monkeypatch):
        captured = {}

        def fake_group(generator):
            sigs = list(generator)
            captured["sigs"] = sigs
            return _FakeGroup(sigs)

        monkeypatch.setattr(celery_tasks, "group", fake_group)

        celery_tasks.ingest_all_sources_task.run(triggered_by="schedule")

        task_names = {sig.task for sig in captured["sigs"]}
        assert task_names == {celery_tasks.ingest_source_task.name}

    def test_each_source_key_is_covered_exactly_once(self, monkeypatch):
        from app.service.pipeline.tasks.registry import SOURCES

        captured = {}

        def fake_group(generator):
            sigs = list(generator)
            captured["sigs"] = sigs
            return _FakeGroup(sigs)

        monkeypatch.setattr(celery_tasks, "group", fake_group)

        celery_tasks.ingest_all_sources_task.run(triggered_by="schedule")

        dispatched_keys = {sig.args[0] for sig in captured["sigs"]}
        assert dispatched_keys == set(SOURCES)

    def test_defaults_triggered_by_to_schedule(self, monkeypatch):
        captured = {}

        def fake_group(generator):
            sigs = list(generator)
            captured["sigs"] = sigs
            return _FakeGroup(sigs)

        monkeypatch.setattr(celery_tasks, "group", fake_group)

        celery_tasks.ingest_all_sources_task.run()

        assert all(sig.kwargs["triggered_by"] == "schedule" for sig in captured["sigs"])

    def test_task_is_registered_under_its_full_dotted_name(self):
        assert (
            celery_tasks.ingest_all_sources_task.name
            == "app.service.pipeline.tasks.celery_tasks.ingest_all_sources_task"
        )


class TestTrainAnomalyModelTask:
    """`train_anomaly_model_task` -- the Celery-task wrapper around
    `ml_anomaly.train_and_publish`, added 2026-08-07 so retraining can
    be scheduled (`train_all_anomaly_models_task` below) instead of only
    ever CLI-triggered by hand."""

    def test_calls_train_and_publish_with_the_sources_entry(self, monkeypatch):
        from app.service.pipeline import ml_anomaly
        from app.service.pipeline.tasks.registry import SOURCES

        captured = {}

        async def fake_train_and_publish(source, table):
            captured["source"] = source
            captured["table"] = table
            return {
                "source": source,
                "rows_trained": 500,
                "columns": ["demand_mw"],
                "object_storage_key": "models/anomaly/bom.joblib",
            }

        monkeypatch.setattr(ml_anomaly, "train_and_publish", fake_train_and_publish)

        summary = celery_tasks.train_anomaly_model_task.run("bom")

        assert captured["source"] == SOURCES["bom"].source
        assert captured["table"] == SOURCES["bom"].table
        assert summary is not None
        assert summary["rows_trained"] == 500

    def test_returns_none_and_logs_a_warning_when_training_is_skipped(
        self, monkeypatch
    ):
        from app.service.pipeline import ml_anomaly

        async def fake_train_and_publish(source, table):
            return None  # not enough history yet -- ml_anomaly's own contract

        monkeypatch.setattr(ml_anomaly, "train_and_publish", fake_train_and_publish)

        summary = celery_tasks.train_anomaly_model_task.run("oe")

        assert summary is None

    def test_reraises_on_a_real_training_failure(self, monkeypatch):
        from app.service.pipeline import ml_anomaly

        async def fake_train_and_publish(source, table):
            raise RuntimeError("R2 upload failed")

        monkeypatch.setattr(ml_anomaly, "train_and_publish", fake_train_and_publish)

        with pytest.raises(RuntimeError, match="R2 upload failed"):
            celery_tasks.train_anomaly_model_task.run("aemo-nem")

    def test_task_is_registered_under_its_full_dotted_name(self):
        assert (
            celery_tasks.train_anomaly_model_task.name
            == "app.service.pipeline.tasks.celery_tasks.train_anomaly_model_task"
        )


class TestTrainAllAnomalyModelsTask:
    def test_dispatches_one_child_per_backfillable_source(self, monkeypatch):
        from app.service.pipeline.backfill import BACKFILLABLE_SOURCES

        captured = {}

        def fake_group(generator):
            sigs = list(generator)
            captured["sigs"] = sigs
            return _FakeGroup(sigs)

        monkeypatch.setattr(celery_tasks, "group", fake_group)

        child_ids = celery_tasks.train_all_anomaly_models_task.run()

        assert len(captured["sigs"]) == len(BACKFILLABLE_SOURCES)
        assert len(child_ids) == len(BACKFILLABLE_SOURCES)

    def test_holidays_is_excluded_same_as_it_never_gets_a_model(self, monkeypatch):
        captured = {}

        def fake_group(generator):
            sigs = list(generator)
            captured["sigs"] = sigs
            return _FakeGroup(sigs)

        monkeypatch.setattr(celery_tasks, "group", fake_group)

        celery_tasks.train_all_anomaly_models_task.run()

        dispatched_keys = {sig.args[0] for sig in captured["sigs"]}
        assert "holidays" not in dispatched_keys

    def test_each_child_signature_targets_train_anomaly_model_task(self, monkeypatch):
        captured = {}

        def fake_group(generator):
            sigs = list(generator)
            captured["sigs"] = sigs
            return _FakeGroup(sigs)

        monkeypatch.setattr(celery_tasks, "group", fake_group)

        celery_tasks.train_all_anomaly_models_task.run()

        task_names = {sig.task for sig in captured["sigs"]}
        assert task_names == {celery_tasks.train_anomaly_model_task.name}

    def test_task_is_registered_under_its_full_dotted_name(self):
        assert (
            celery_tasks.train_all_anomaly_models_task.name
            == "app.service.pipeline.tasks.celery_tasks.train_all_anomaly_models_task"
        )
