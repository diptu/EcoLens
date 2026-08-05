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
