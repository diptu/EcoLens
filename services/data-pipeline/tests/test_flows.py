from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.service.pipeline import flows

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    """Each call to `execute` pops the next queued row from `rows`."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        self.queries.append((str(query), params or {}))
        row = self.rows.pop(0) if self.rows else None
        return _FakeResult(row)


class _FakeSessionCtx:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc_info):
        return False


class TestIngestSource:
    async def test_returns_the_most_recent_run_id_for_the_source(self, monkeypatch):
        calls = {}

        async def fake_run_source(key, **kwargs):
            calls["key"] = key
            calls["kwargs"] = kwargs

        session = _FakeSession(rows=[("run-abc",)])
        monkeypatch.setattr(flows, "run_source", fake_run_source)
        monkeypatch.setattr(flows, "get_session", lambda: _FakeSessionCtx(session))

        run_id = await flows.ingest_source.fn("bom")

        assert run_id == "run-abc"
        assert calls["key"] == "bom"
        assert calls["kwargs"] == {"triggered_by": "schedule"}
        _, params = session.queries[0]
        assert params["source"] == "bom"

    async def test_returns_empty_string_when_no_row_found(self, monkeypatch):
        async def fake_run_source(key, **kwargs):
            pass

        session = _FakeSession(rows=[None])
        monkeypatch.setattr(flows, "run_source", fake_run_source)
        monkeypatch.setattr(flows, "get_session", lambda: _FakeSessionCtx(session))

        run_id = await flows.ingest_source.fn("bom")

        assert run_id == ""


class TestWaitForSync:
    async def test_returns_unknown_immediately_for_empty_run_id(self, monkeypatch):
        result = await flows.wait_for_sync.fn("")

        assert result == "unknown"

    async def test_returns_terminal_status_without_waiting_the_full_timeout(
        self, monkeypatch
    ):
        session = _FakeSession(rows=[("success",)])
        monkeypatch.setattr(flows, "get_session", lambda: _FakeSessionCtx(session))

        result = await flows.wait_for_sync.fn(
            "run-1", timeout_seconds=60, poll_seconds=0.01
        )

        assert result == "success"

    async def test_times_out_when_status_never_reaches_terminal(self, monkeypatch):
        session = _FakeSession(rows=[("running",)] * 100)
        monkeypatch.setattr(flows, "get_session", lambda: _FakeSessionCtx(session))

        result = await flows.wait_for_sync.fn(
            "run-1", timeout_seconds=0.05, poll_seconds=0.01
        )

        assert result == "timeout"


class TestDbtBuildTask:
    def test_calls_run_dbt_with_settings_project_dir(self, monkeypatch):
        captured = {}

        def fake_run_dbt(subcommand, project_dir, target, extra_args):
            captured.update(
                subcommand=subcommand,
                project_dir=project_dir,
                target=target,
                extra_args=extra_args,
            )
            return 0

        monkeypatch.setattr(flows, "run_dbt", fake_run_dbt)

        exit_code = flows.dbt_build_task.fn(target="prod")

        assert exit_code == 0
        assert captured["subcommand"] == "build"
        assert captured["target"] == "prod"


class TestPublishTrainingTrigger:
    async def test_publishes_payload_with_anomaly_count_and_window(self, monkeypatch):
        session = _FakeSession(rows=[(3,)])
        monkeypatch.setattr(flows, "get_session", lambda: _FakeSessionCtx(session))

        published = {}

        async def fake_publish(payload):
            published.update(payload)

        monkeypatch.setattr(flows, "publish_training_trigger_event", fake_publish)

        await flows.publish_training_trigger.fn(["NSW1"], 24)

        assert published["event"] == "warehouse.transform.completed"
        assert published["dataset"] == "raw_marts.fct_energy_demand"
        assert published["regions"] == ["NSW1"]
        assert published["anomalies_flagged"] == 3
        assert "window_since" in published
        assert "window_until" in published
        assert published["window_since"] < published["window_until"]

    async def test_defaults_anomaly_count_to_zero_when_no_row_returned(
        self, monkeypatch
    ):
        session = _FakeSession(rows=[None])
        monkeypatch.setattr(flows, "get_session", lambda: _FakeSessionCtx(session))

        published = {}

        async def fake_publish(payload):
            published.update(payload)

        monkeypatch.setattr(flows, "publish_training_trigger_event", fake_publish)

        await flows.publish_training_trigger.fn(["NSW1"], 24)

        assert published["anomalies_flagged"] == 0


class TestTrainingDue:
    def test_true_when_no_production_version_exists(self, monkeypatch):
        monkeypatch.setattr(flows, "get_version_in_stage", lambda name, stage: None)

        assert flows.training_due.fn("lstm_demand") is True

    def test_true_when_current_version_is_older_than_min_age(self, monkeypatch):
        old_ts_ms = (datetime.now(UTC) - timedelta(days=30)).timestamp() * 1000

        class _Version:
            creation_timestamp = old_ts_ms

        monkeypatch.setattr(
            flows, "get_version_in_stage", lambda name, stage: _Version()
        )

        assert flows.training_due.fn("lstm_demand", min_age_days=7) is True

    def test_false_when_current_version_is_recent(self, monkeypatch):
        recent_ts_ms = (datetime.now(UTC) - timedelta(hours=1)).timestamp() * 1000

        class _Version:
            creation_timestamp = recent_ts_ms

        monkeypatch.setattr(
            flows, "get_version_in_stage", lambda name, stage: _Version()
        )

        assert flows.training_due.fn("lstm_demand", min_age_days=7) is False


class TestTrainAndRegisterTask:
    async def test_returns_the_run_id(self, monkeypatch):
        class _Result:
            run_id = "run-xyz"

        async def fake_train_and_register(model_name, regions, register):
            assert model_name == "lstm_demand"
            assert regions == ["NSW1"]
            assert register is True
            return _Result()

        monkeypatch.setattr(flows, "train_and_register", fake_train_and_register)

        run_id = await flows.train_and_register_task.fn("lstm_demand", ["NSW1"])

        assert run_id == "run-xyz"


class TestDailyDemandFlow:
    async def test_trains_when_due_and_touches_every_source(self, monkeypatch):
        calls = {
            "ingest": [],
            "wait": [],
            "dbt": 0,
            "train": 0,
            "train_tft": 0,
            "publish": [],
        }

        async def fake_ingest_source(key):
            calls["ingest"].append(key)
            return f"run-{key}"

        async def fake_wait_for_sync(run_id):
            calls["wait"].append(run_id)
            return "success"

        def fake_dbt_build_task(target):
            calls["dbt"] += 1
            return 0

        async def fake_publish_training_trigger(regions, window_hours, *, architecture):
            calls["publish"].append((regions, window_hours, architecture))

        def fake_training_due(model_name):
            return True

        async def fake_train_and_register_task(model_name, regions):
            calls["train"] += 1
            return "run-trained"

        async def fake_train_and_register_tft_task(model_name, regions):
            calls["train_tft"] += 1
            return "run-trained-tft"

        monkeypatch.setattr(flows, "ingest_source", fake_ingest_source)
        monkeypatch.setattr(flows, "wait_for_sync", fake_wait_for_sync)
        monkeypatch.setattr(flows, "dbt_build_task", fake_dbt_build_task)
        monkeypatch.setattr(
            flows, "publish_training_trigger", fake_publish_training_trigger
        )
        monkeypatch.setattr(flows, "training_due", fake_training_due)
        monkeypatch.setattr(
            flows, "train_and_register_task", fake_train_and_register_task
        )
        monkeypatch.setattr(
            flows, "train_and_register_tft_task", fake_train_and_register_tft_task
        )

        await flows.daily_demand.fn(regions=["NSW1"], target="dev")

        assert calls["ingest"] == list(flows.DEMAND_TRAINING_SOURCES)
        assert calls["wait"] == [f"run-{k}" for k in flows.DEMAND_TRAINING_SOURCES]
        assert calls["dbt"] == 1
        assert calls["train"] == 1
        assert calls["train_tft"] == 1
        assert calls["publish"] == [
            (["NSW1"], get_settings().incremental_train_window_hours, "lstm"),
            (["NSW1"], get_settings().incremental_train_window_hours, "tft"),
        ]

    async def test_skips_training_when_not_due(self, monkeypatch):
        calls = {"train": 0, "train_tft": 0}

        async def fake_ingest_source(key):
            return f"run-{key}"

        async def fake_wait_for_sync(run_id):
            return "success"

        def fake_dbt_build_task(target):
            return 0

        async def fake_publish_training_trigger(regions, window_hours, *, architecture):
            pass

        def fake_training_due(model_name):
            return False

        async def fake_train_and_register_task(model_name, regions):
            calls["train"] += 1
            return "run-trained"

        async def fake_train_and_register_tft_task(model_name, regions):
            calls["train_tft"] += 1
            return "run-trained-tft"

        monkeypatch.setattr(flows, "ingest_source", fake_ingest_source)
        monkeypatch.setattr(flows, "wait_for_sync", fake_wait_for_sync)
        monkeypatch.setattr(flows, "dbt_build_task", fake_dbt_build_task)
        monkeypatch.setattr(
            flows, "publish_training_trigger", fake_publish_training_trigger
        )
        monkeypatch.setattr(flows, "training_due", fake_training_due)
        monkeypatch.setattr(
            flows, "train_and_register_task", fake_train_and_register_task
        )
        monkeypatch.setattr(
            flows, "train_and_register_tft_task", fake_train_and_register_tft_task
        )

        await flows.daily_demand.fn(regions=["NSW1"], target="dev")

        assert calls["train"] == 0
        assert calls["train_tft"] == 0

    async def test_skips_publishing_the_training_trigger_when_dbt_build_fails(
        self, monkeypatch
    ):
        calls = {"publish": 0}

        async def fake_ingest_source(key):
            return f"run-{key}"

        async def fake_wait_for_sync(run_id):
            return "success"

        def fake_dbt_build_task(target):
            return 1  # dbt failed

        async def fake_publish_training_trigger(regions, window_hours, *, architecture):
            calls["publish"] += 1

        def fake_training_due(model_name):
            return False

        async def fake_train_and_register_task(model_name, regions):
            return "run-trained"

        async def fake_train_and_register_tft_task(model_name, regions):
            return "run-trained-tft"

        monkeypatch.setattr(flows, "ingest_source", fake_ingest_source)
        monkeypatch.setattr(flows, "wait_for_sync", fake_wait_for_sync)
        monkeypatch.setattr(flows, "dbt_build_task", fake_dbt_build_task)
        monkeypatch.setattr(
            flows, "publish_training_trigger", fake_publish_training_trigger
        )
        monkeypatch.setattr(flows, "training_due", fake_training_due)
        monkeypatch.setattr(
            flows, "train_and_register_task", fake_train_and_register_task
        )
        monkeypatch.setattr(
            flows, "train_and_register_tft_task", fake_train_and_register_tft_task
        )

        await flows.daily_demand.fn(regions=["NSW1"], target="dev")

        assert calls["publish"] == 0


class TestIncrementalRetrainTriggerFlow:
    async def test_publishes_for_every_architecture_after_a_successful_build(
        self, monkeypatch
    ):
        calls = {"dbt": 0, "publish": []}

        def fake_dbt_build_task(target):
            calls["dbt"] += 1
            return 0

        async def fake_publish_training_trigger(regions, window_hours, *, architecture):
            calls["publish"].append((regions, window_hours, architecture))

        monkeypatch.setattr(flows, "dbt_build_task", fake_dbt_build_task)
        monkeypatch.setattr(
            flows, "publish_training_trigger", fake_publish_training_trigger
        )

        await flows.incremental_retrain_trigger.fn(regions=["WEM"], target="dev")

        assert calls["dbt"] == 1
        assert calls["publish"] == [
            (["WEM"], get_settings().incremental_train_window_hours, "lstm"),
            (["WEM"], get_settings().incremental_train_window_hours, "tft"),
        ]

    async def test_skips_publishing_when_dbt_build_fails(self, monkeypatch):
        calls = {"publish": 0}

        def fake_dbt_build_task(target):
            return 1

        async def fake_publish_training_trigger(regions, window_hours, *, architecture):
            calls["publish"] += 1

        monkeypatch.setattr(flows, "dbt_build_task", fake_dbt_build_task)
        monkeypatch.setattr(
            flows, "publish_training_trigger", fake_publish_training_trigger
        )

        await flows.incremental_retrain_trigger.fn(regions=["WEM"], target="dev")

        assert calls["publish"] == 0

    async def test_defaults_regions_and_target_from_settings(self, monkeypatch):
        captured = {}

        def fake_dbt_build_task(target):
            captured["target"] = target
            return 0

        async def fake_publish_training_trigger(regions, window_hours, *, architecture):
            captured.setdefault("regions", regions)

        monkeypatch.setattr(flows, "dbt_build_task", fake_dbt_build_task)
        monkeypatch.setattr(
            flows, "publish_training_trigger", fake_publish_training_trigger
        )

        await flows.incremental_retrain_trigger.fn()

        settings = get_settings()
        assert captured["target"] == settings.dbt_target
        assert captured["regions"] == settings.model_default_regions
