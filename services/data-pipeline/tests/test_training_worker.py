from __future__ import annotations

import pytest

from app.service import training_worker
from app.core.config import get_settings
from app.service.ml.train import TrainAndRegisterResult

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeSession:
    def __init__(self):
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        self.queries.append((str(query), params or {}))


class _FakeSessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def fake_training_log_session(monkeypatch):
    """`handle_training_trigger` now writes `meta._training_log` rows
    (Model Operations TODO.md Phase 4) -- fake the DB session for every
    test in this module so none of them need a real Postgres. Tests
    that care about the logged rows request this fixture explicitly to
    inspect `.queries`."""
    session = _FakeSession()
    monkeypatch.setattr(
        training_worker, "get_session", lambda: _FakeSessionCtx(session)
    )
    return session


async def test_run_consumes_events_and_closes_the_connection_on_exit(monkeypatch):
    calls = []

    async def fake_consume(handler):
        calls.append(("consume", handler))

    async def fake_close():
        calls.append(("close", None))

    monkeypatch.setattr(
        training_worker, "consume_training_trigger_events", fake_consume
    )
    monkeypatch.setattr(training_worker, "close_rabbitmq", fake_close)

    await training_worker.run()

    assert calls[0][0] == "consume"
    assert calls[0][1] is training_worker.handle_training_trigger
    assert calls[1] == ("close", None)


async def test_run_closes_the_connection_even_if_consuming_raises(monkeypatch):
    async def fake_consume(handler):
        raise RuntimeError("broker connection dropped")

    closed = []

    async def fake_close():
        closed.append(True)

    monkeypatch.setattr(
        training_worker, "consume_training_trigger_events", fake_consume
    )
    monkeypatch.setattr(training_worker, "close_rabbitmq", fake_close)

    with pytest.raises(RuntimeError, match="broker connection dropped"):
        await training_worker.run()

    assert closed == [True]


class TestHandleTrainingTrigger:
    async def test_resolves_regions_and_since_from_payload_and_trains(
        self, monkeypatch
    ):
        captured = {}

        async def fake_train_and_register_incremental(model_name, regions, since):
            captured["model_name"] = model_name
            captured["regions"] = regions
            captured["since"] = since
            return TrainAndRegisterResult(
                run_id="run-1", model_version="2", test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            training_worker,
            "train_and_register_incremental",
            fake_train_and_register_incremental,
        )

        payload = {"regions": ["NSW1"], "window_since": "2026-08-01T00:00:00+00:00"}
        await training_worker.handle_training_trigger(payload)

        assert captured["model_name"] == get_settings().mlflow_registry_model_name
        assert captured["regions"] == ["NSW1"]
        assert str(captured["since"]) == "2026-08-01 00:00:00+00:00"

    async def test_falls_back_to_default_regions_and_computed_window_when_absent(
        self, monkeypatch
    ):
        captured = {}

        async def fake_train_and_register_incremental(model_name, regions, since):
            captured["regions"] = regions
            captured["since"] = since
            return TrainAndRegisterResult(
                run_id="run-1", model_version=None, test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            training_worker,
            "train_and_register_incremental",
            fake_train_and_register_incremental,
        )

        await training_worker.handle_training_trigger({})

        settings = get_settings()
        assert captured["regions"] == settings.model_default_regions
        assert captured["since"] is not None


class TestTrainingLog:
    async def test_logs_a_running_row_then_closes_it_out_as_success(
        self, monkeypatch, fake_training_log_session
    ):
        async def fake_train(model_name, regions, since):
            return TrainAndRegisterResult(
                run_id="run-1", model_version="4", test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_train
        )

        payload = {
            "regions": ["NSW1"],
            "window_since": "2026-08-01T00:00:00+00:00",
            "window_until": "2026-08-02T00:00:00+00:00",
            "triggered_by": "manual",
        }
        await training_worker.handle_training_trigger(payload)

        insert_sql, insert_params = fake_training_log_session.queries[0]
        assert "INSERT INTO meta._training_log" in insert_sql
        assert insert_params["triggered_by"] == "manual"
        assert insert_params["regions"] == '["NSW1"]'

        update_sql, update_params = fake_training_log_session.queries[1]
        assert "UPDATE meta._training_log" in update_sql
        assert update_params["status"] == "success"
        assert update_params["run_id"] == "run-1"
        assert update_params["model_version"] == "4"

    async def test_defaults_triggered_by_to_schedule_when_absent(
        self, monkeypatch, fake_training_log_session
    ):
        async def fake_train(model_name, regions, since):
            return TrainAndRegisterResult(
                run_id="run-1", model_version=None, test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_train
        )

        await training_worker.handle_training_trigger({})

        _, insert_params = fake_training_log_session.queries[0]
        assert insert_params["triggered_by"] == "schedule"

    async def test_logs_a_failed_row_and_still_reraises_when_training_fails(
        self, monkeypatch, fake_training_log_session
    ):
        async def fake_train(model_name, regions, since):
            raise ValueError("no warm-startable version yet")

        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_train
        )

        with pytest.raises(ValueError, match="no warm-startable version"):
            await training_worker.handle_training_trigger({"regions": ["NSW1"]})

        update_sql, update_params = fake_training_log_session.queries[1]
        assert "UPDATE meta._training_log" in update_sql
        assert update_params["status"] == "failed"
        assert "no warm-startable version yet" in update_params["error_message"]
