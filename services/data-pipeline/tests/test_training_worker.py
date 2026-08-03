from __future__ import annotations

import pytest

from app.service import training_worker
from app.core.config import get_settings
from app.service.ml.train import TrainAndRegisterResult

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


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
