"""Ported verbatim from data-pipeline's identical `tests/
test_training_worker.py` as part of the training-code migration --
`app.service.training_worker` here is a byte-for-byte port of that
module (see its own docstring), so the same test cases apply unchanged.

`TestHandleTrainingTrigger`'s `timesfm_correction` dispatch test is new
(2026-08-11, not part of the original port) -- data-pipeline's version
of this module predates `service/ml/timesfm_correction.py` entirely."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.config import get_settings
from app.service import training_worker
from app.service.model import actions as model_actions
from app.service.ml.train import TrainAndRegisterResult
from app.service.ml.timesfm_correction import TrainAndRegisterCorrectionResult

pytestmark = pytest.mark.anyio

# Captured once, before any test's `fake_live_eval_gate` autouse fixture
# patches it away -- the one test that wants the REAL `_run_live_
# evaluation_gate` (to verify its own internal exception-catching)
# restores this reference explicitly.
_real_run_live_evaluation_gate = training_worker._run_live_evaluation_gate


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeSession:
    def __init__(self):
        self.queries: list[tuple[str, dict]] = []
        self.committed = 0

    async def execute(self, query, params=None):
        self.queries.append((str(query), params or {}))

    async def commit(self):
        self.committed += 1


class _FakeSessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def fake_training_log_session(monkeypatch):
    """`handle_training_trigger` writes `meta._training_log` rows via
    `log_training_start`/`log_training_finish` (`service/model/
    actions.py` -- moved there from this module so `train_energy_
    forecast.py`'s CLI-triggered runs can log too, see that module's own
    docstring). Fake the DB session for every test in this module so
    none of them need a real Postgres. Tests that care about the logged
    rows request this fixture explicitly to inspect `.queries`."""
    session = _FakeSession()
    monkeypatch.setattr(
        model_actions, "get_log_session", lambda: _FakeSessionCtx(session)
    )
    return session


@pytest.fixture(autouse=True)
def fake_live_eval_gate(monkeypatch):
    """`handle_training_trigger` runs the live evaluation gate after a
    successful registration -- stub it out to a no-op by default so
    every test in this module stays fast/hermetic (no real MLflow/DB
    calls) unless a test explicitly wants to observe it, in which case
    it overrides this fixture's patch itself."""
    calls = []

    async def fake_gate(architecture, model_name, version, regions):
        calls.append((architecture, model_name, version, regions))

    monkeypatch.setattr(training_worker, "_run_live_evaluation_gate", fake_gate)
    return calls


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


@dataclass
class _FakeModelVersion:
    """Lightweight stand-in for `mlflow.entities.model_registry.
    ModelVersion` -- `_resolve_max_acceptable_mape` only ever reads
    `.run_id`/`.tags` off whatever `get_version_in_stage` returns."""

    run_id: str | None
    tags: dict[str, str]


class TestResolveMaxAcceptableMape:
    """Real bug #1, confirmed live 2026-08-11 (`Settings.live_eval_gate_
    max_regression_pct`'s own docstring): `_run_live_evaluation_gate`
    used to call `run_live_evaluation_gate` without ever passing `max_
    acceptable_mape`, so the "never force-skippable" live-eval gate
    could never actually fail on real accuracy -- only on a total
    evaluation failure. `_resolve_max_acceptable_mape` is the real fix.

    Real bug #2, confirmed live 2026-08-12 against an actual promotion
    attempt: this used to fall back to Production's logged `test_mape`
    (an easier, single-split metric) when its `eval_gate_mape` tag (real
    walk-forward) was absent, comparing a candidate's real walk-forward
    MAPE against an apples-to-oranges threshold -- rejected v16 (11.01
    real walk-forward, roughly a wash against v7's *own* ~11.24 computed
    the same way) against `v7's test_mape (8.19) * 1.2 = 9.83`. The
    fallback is gone; these tests pin the three real cases that remain.
    """

    def test_returns_none_when_no_production_version_exists(self, monkeypatch):
        monkeypatch.setattr(
            training_worker, "get_version_in_stage", lambda *a, **k: None
        )

        result = training_worker._resolve_max_acceptable_mape(
            "lstm_demand", get_settings()
        )

        assert result is None

    def test_uses_the_real_eval_gate_mape_tag_when_present(self, monkeypatch):
        monkeypatch.setattr(
            training_worker,
            "get_version_in_stage",
            lambda *a, **k: _FakeModelVersion(
                run_id="run-1", tags={"eval_gate_mape": "10.0"}
            ),
        )
        settings = get_settings().model_copy(
            update={"live_eval_gate_max_regression_pct": 20.0}
        )

        result = training_worker._resolve_max_acceptable_mape("lstm_demand", settings)

        assert result == pytest.approx(12.0)

    def test_returns_none_when_the_tag_is_absent_even_if_test_mape_exists(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            training_worker,
            "get_version_in_stage",
            lambda *a, **k: _FakeModelVersion(run_id="run-1", tags={}),
        )

        result = training_worker._resolve_max_acceptable_mape(
            "lstm_demand", get_settings()
        )

        assert result is None


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

    async def test_dispatches_to_lstm_by_default(self, monkeypatch):
        calls = []

        async def fake_lstm(model_name, regions, since):
            calls.append("lstm")
            return TrainAndRegisterResult(
                run_id="run-1", model_version="1", test_metrics={}, final_val_mape=None
            )

        async def fake_tft(model_name, regions, since):
            calls.append("tft")
            return TrainAndRegisterResult(
                run_id="run-1", model_version="1", test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_lstm
        )
        monkeypatch.setattr(
            training_worker, "train_and_register_tft_incremental", fake_tft
        )

        await training_worker.handle_training_trigger({"regions": ["NSW1"]})

        assert calls == ["lstm"]

    async def test_dispatches_to_tft_when_architecture_is_tft(self, monkeypatch):
        calls = []
        captured = {}

        async def fake_lstm(model_name, regions, since):
            calls.append("lstm")
            return TrainAndRegisterResult(
                run_id="run-1", model_version="1", test_metrics={}, final_val_mape=None
            )

        async def fake_tft(model_name, regions, since):
            calls.append("tft")
            captured["model_name"] = model_name
            return TrainAndRegisterResult(
                run_id="run-1", model_version="1", test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_lstm
        )
        monkeypatch.setattr(
            training_worker, "train_and_register_tft_incremental", fake_tft
        )

        await training_worker.handle_training_trigger(
            {"regions": ["NSW1"], "architecture": "tft"}
        )

        assert calls == ["tft"]
        assert captured["model_name"] == training_worker.TFT_MODEL_NAME

    async def test_dispatches_to_timesfm_correction_when_architecture_is_timesfm_correction(
        self, monkeypatch
    ):
        calls = []
        captured = {}

        async def fake_lstm(model_name, regions, since):
            calls.append("lstm")
            return TrainAndRegisterResult(
                run_id="run-1", model_version="1", test_metrics={}, final_val_mape=None
            )

        async def fake_tft(model_name, regions, since):
            calls.append("tft")
            return TrainAndRegisterResult(
                run_id="run-1", model_version="1", test_metrics={}, final_val_mape=None
            )

        async def fake_correction(model_name, regions, *, since):
            calls.append("timesfm_correction")
            captured["model_name"] = model_name
            captured["regions"] = regions
            captured["since"] = since
            return TrainAndRegisterCorrectionResult(
                run_id="run-1", model_version="1", metrics={}
            )

        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_lstm
        )
        monkeypatch.setattr(
            training_worker, "train_and_register_tft_incremental", fake_tft
        )
        monkeypatch.setattr(
            training_worker, "train_and_register_correction", fake_correction
        )

        await training_worker.handle_training_trigger(
            {"regions": ["NSW1"], "architecture": "timesfm_correction"}
        )

        assert calls == ["timesfm_correction"]
        assert captured["model_name"] == training_worker.TIMESFM_CORRECTION_MODEL_NAME
        assert captured["regions"] == ["NSW1"]

    async def test_full_retrain_dispatches_to_the_real_from_scratch_lstm_trainer(
        self, monkeypatch
    ):
        """2026-08-11: `full_retrain=True` is the real feature behind
        the dashboard's "Train a new version" tab finally having a
        trigger endpoint -- confirms it calls `ml.train.
        train_and_register` (the same function `ecolens-forecast train`
        uses), not the incremental warm-start path."""
        calls = []

        async def fake_full(model_name, regions, *, since):
            calls.append("full_lstm")
            return TrainAndRegisterResult(
                run_id="run-1", model_version="1", test_metrics={}, final_val_mape=None
            )

        async def fake_incremental(model_name, regions, since):
            calls.append("incremental_lstm")
            return TrainAndRegisterResult(
                run_id="run-1", model_version="1", test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(training_worker, "train_and_register", fake_full)
        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_incremental
        )

        await training_worker.handle_training_trigger(
            {"regions": ["NSW1"], "full_retrain": True}
        )

        assert calls == ["full_lstm"]

    async def test_full_retrain_dispatches_to_the_real_from_scratch_tft_trainer(
        self, monkeypatch
    ):
        calls = []
        captured = {}

        async def fake_full_tft(model_name, regions, *, since):
            calls.append("full_tft")
            captured["model_name"] = model_name
            return TrainAndRegisterResult(
                run_id="run-1", model_version="1", test_metrics={}, final_val_mape=None
            )

        async def fake_incremental_tft(model_name, regions, since):
            calls.append("incremental_tft")
            return TrainAndRegisterResult(
                run_id="run-1", model_version="1", test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(training_worker, "train_and_register_tft", fake_full_tft)
        monkeypatch.setattr(
            training_worker, "train_and_register_tft_incremental", fake_incremental_tft
        )

        await training_worker.handle_training_trigger(
            {"regions": ["NSW1"], "architecture": "tft", "full_retrain": True}
        )

        assert calls == ["full_tft"]
        assert captured["model_name"] == training_worker.TFT_MODEL_NAME

    async def test_full_retrain_does_not_change_timesfm_correction_dispatch(
        self, monkeypatch
    ):
        """No real "from scratch vs incremental" distinction for the
        correction layer (`TrainRequest.full_retrain`'s own docstring)
        -- confirms `full_retrain=True` still calls the exact same
        `train_and_register_correction` an incremental trigger would."""
        calls = []

        async def fake_correction(model_name, regions, *, since):
            calls.append("timesfm_correction")
            return TrainAndRegisterCorrectionResult(
                run_id="run-1", model_version="1", metrics={}
            )

        async def fail_if_called(*args, **kwargs):
            raise AssertionError("full-retrain LSTM/TFT trainer should not be called")

        monkeypatch.setattr(
            training_worker, "train_and_register_correction", fake_correction
        )
        monkeypatch.setattr(training_worker, "train_and_register", fail_if_called)
        monkeypatch.setattr(training_worker, "train_and_register_tft", fail_if_called)

        await training_worker.handle_training_trigger(
            {
                "regions": ["NSW1"],
                "architecture": "timesfm_correction",
                "full_retrain": True,
            }
        )

        assert calls == ["timesfm_correction"]

    async def test_full_retrain_defaults_to_false_when_absent(self, monkeypatch):
        """Every event published before `full_retrain` existed --
        including every automatic post-dbt-build event `services/
        waerehouse` still publishes today -- has no such key at all;
        confirms that correctly keeps behaving as an incremental
        fine-tune, not an `AttributeError`/`KeyError` or an accidental
        full retrain."""
        calls = []

        async def fake_incremental(model_name, regions, since):
            calls.append("incremental_lstm")
            return TrainAndRegisterResult(
                run_id="run-1", model_version="1", test_metrics={}, final_val_mape=None
            )

        async def fail_if_called(*args, **kwargs):
            raise AssertionError("full-retrain trainer should not be called")

        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_incremental
        )
        monkeypatch.setattr(training_worker, "train_and_register", fail_if_called)

        await training_worker.handle_training_trigger({"regions": ["NSW1"]})

        assert calls == ["incremental_lstm"]

    async def test_runs_the_live_eval_gate_after_a_successful_registration(
        self, monkeypatch, fake_live_eval_gate
    ):
        async def fake_train(model_name, regions, since):
            return TrainAndRegisterResult(
                run_id="run-1", model_version="7", test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_train
        )

        await training_worker.handle_training_trigger(
            {"regions": ["NSW1"], "architecture": "lstm"}
        )

        assert fake_live_eval_gate == [
            ("lstm", get_settings().mlflow_registry_model_name, "7", ["NSW1"])
        ]

    async def test_skips_the_live_eval_gate_when_nothing_was_registered(
        self, monkeypatch, fake_live_eval_gate
    ):
        async def fake_train(model_name, regions, since):
            return TrainAndRegisterResult(
                run_id="run-1", model_version=None, test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_train
        )

        await training_worker.handle_training_trigger({"regions": ["NSW1"]})

        assert fake_live_eval_gate == []

    async def test_a_failing_live_eval_gate_does_not_fail_the_training_run(
        self, monkeypatch
    ):
        # Restore the REAL `_run_live_evaluation_gate` for this one test
        # -- the module's `fake_live_eval_gate` autouse fixture stubs it
        # to a no-op by default, which would never actually exercise the
        # exception-catching behavior this test wants to verify.
        monkeypatch.setattr(
            training_worker,
            "_run_live_evaluation_gate",
            _real_run_live_evaluation_gate,
        )

        async def fake_train(model_name, regions, since):
            return TrainAndRegisterResult(
                run_id="run-1", model_version="7", test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_train
        )

        def fake_load_registered_model(model_name, version):
            raise RuntimeError("MLflow unreachable")

        monkeypatch.setattr(
            training_worker, "load_registered_model", fake_load_registered_model
        )

        # No exception should propagate -- `_run_live_evaluation_gate`
        # catches and logs internally.
        await training_worker.handle_training_trigger({"regions": ["NSW1"]})

    async def test_live_eval_gate_threads_a_real_relative_threshold_through(
        self, monkeypatch
    ):
        """End-to-end version of `TestResolveMaxAcceptableMape`'s unit
        coverage: confirms the real (unmocked) `_run_live_evaluation_
        gate` actually resolves and passes a non-`None` `max_acceptable_
        mape` to `run_live_evaluation_gate`, and that a candidate worse
        than that ceiling comes back `passed=False` -- proving the gate
        can now actually fail on real accuracy, not just on evaluation
        being unreachable (the real bug this fix closes)."""
        monkeypatch.setattr(
            training_worker,
            "_run_live_evaluation_gate",
            _real_run_live_evaluation_gate,
        )

        async def fake_train(model_name, regions, since):
            return TrainAndRegisterResult(
                run_id="run-1", model_version="7", test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            training_worker, "train_and_register_incremental", fake_train
        )

        class _FakeLoadedModel:
            horizon = 48

        class _FakeForecaster:
            model = _FakeLoadedModel()

        monkeypatch.setattr(
            training_worker,
            "load_registered_model",
            lambda model_name, version: _FakeForecaster(),
        )
        monkeypatch.setattr(
            training_worker,
            "get_version_in_stage",
            lambda *a, **k: _FakeModelVersion(
                run_id="prod-run", tags={"eval_gate_mape": "5.0"}
            ),
        )

        captured = {}

        async def fake_run_live_evaluation_gate(
            forecaster, model_name, version, regions, horizon, *, max_acceptable_mape=None
        ):
            captured["max_acceptable_mape"] = max_acceptable_mape
            from app.service.ml.evaluate import LiveEvaluationGateResult

            # Worse than the 5.0 * 1.2 = 6.0 ceiling -- a real regression.
            return LiveEvaluationGateResult(passed=False, overall_mape=9.0, reports=[])

        monkeypatch.setattr(
            training_worker,
            "run_live_evaluation_gate",
            fake_run_live_evaluation_gate,
        )

        await training_worker.handle_training_trigger(
            {"regions": ["NSW1"], "architecture": "lstm"}
        )

        assert captured["max_acceptable_mape"] == pytest.approx(6.0)


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
