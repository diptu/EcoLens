from __future__ import annotations

import pandas as pd
import pytest
import torch

from app.core.config import get_settings
from app.service.ml import incremental_tft
from app.service.ml.incremental_tft import (
    TFTWarmStart,
    get_warm_start_tft,
    train_and_register_tft_incremental,
)
from app.service.ml.train import TrainAndRegisterResult

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeVersion:
    def __init__(self, run_id: str, version: str = "3") -> None:
        self.run_id = run_id
        self.version = version


class _FakeRunData:
    def __init__(self, params: dict[str, str]) -> None:
        self.params = params


class _FakeRun:
    def __init__(self, params: dict[str, str]) -> None:
        self.data = _FakeRunData(params)


class _FakeMlflowClient:
    def __init__(self, run_id: str, params: dict[str, str]) -> None:
        self._run_id = run_id
        self._params = params

    def get_run(self, run_id: str) -> _FakeRun:
        assert run_id == self._run_id
        return _FakeRun(self._params)


_FAKE_PARAMS = {
    "hidden_size": "8",
    "n_heads": "2",
    "dropout": "0.0",
    "horizon": "4",
    "lookback": "8",
}


class TestGetWarmStartTft:
    def test_returns_none_when_no_production_or_staging_version_exists(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            incremental_tft, "get_version_in_stage", lambda name, stage: None
        )

        assert get_warm_start_tft("lstm_demand_tft") is None

    def test_uses_production_when_available(self, monkeypatch):
        calls = []

        def fake_get_version_in_stage(name, stage):
            calls.append(stage)
            return _FakeVersion("run-prod") if stage == "Production" else None

        monkeypatch.setattr(
            incremental_tft, "get_version_in_stage", fake_get_version_in_stage
        )
        monkeypatch.setattr(
            incremental_tft,
            "MlflowClient",
            lambda: _FakeMlflowClient("run-prod", _FAKE_PARAMS),
        )
        state_dict = {"weight": torch.zeros(1)}
        monkeypatch.setattr(
            incremental_tft.mlflow.artifacts,
            "download_artifacts",
            lambda **kwargs: "/fake/dir",
        )
        monkeypatch.setattr(
            incremental_tft.torch,
            "load",
            lambda path, map_location=None, weights_only=None: state_dict,
        )

        warm_start = get_warm_start_tft("lstm_demand_tft")

        assert calls == ["Production"]
        assert warm_start is not None
        assert warm_start.stage == "Production"
        assert warm_start.run_id == "run-prod"
        assert warm_start.n_heads == 2

    def test_falls_back_to_staging_when_production_is_empty(self, monkeypatch):
        calls = []

        def fake_get_version_in_stage(name, stage):
            calls.append(stage)
            return None if stage == "Production" else _FakeVersion("run-staging")

        monkeypatch.setattr(
            incremental_tft, "get_version_in_stage", fake_get_version_in_stage
        )
        monkeypatch.setattr(
            incremental_tft,
            "MlflowClient",
            lambda: _FakeMlflowClient("run-staging", _FAKE_PARAMS),
        )
        state_dict = {"weight": torch.zeros(1)}
        monkeypatch.setattr(
            incremental_tft.mlflow.artifacts,
            "download_artifacts",
            lambda **kwargs: "/fake/dir",
        )
        monkeypatch.setattr(
            incremental_tft.torch,
            "load",
            lambda path, map_location=None, weights_only=None: state_dict,
        )

        warm_start = get_warm_start_tft("lstm_demand_tft")

        assert calls == ["Production", "Staging"]
        assert warm_start is not None
        assert warm_start.stage == "Staging"
        assert warm_start.run_id == "run-staging"
        assert warm_start.state_dict is state_dict
        assert warm_start.hidden_size == 8
        assert warm_start.n_heads == 2
        assert warm_start.dropout == 0.0
        assert warm_start.horizon == 4
        assert warm_start.lookback == 8

    def test_explicit_stage_is_used_without_fallback(self, monkeypatch):
        calls = []

        def fake_get_version_in_stage(name, stage):
            calls.append(stage)
            return _FakeVersion("run-staging")

        monkeypatch.setattr(
            incremental_tft, "get_version_in_stage", fake_get_version_in_stage
        )
        monkeypatch.setattr(
            incremental_tft,
            "MlflowClient",
            lambda: _FakeMlflowClient("run-staging", _FAKE_PARAMS),
        )
        monkeypatch.setattr(
            incremental_tft.mlflow.artifacts,
            "download_artifacts",
            lambda **kwargs: "/fake/dir",
        )
        monkeypatch.setattr(
            incremental_tft.torch,
            "load",
            lambda path, map_location=None, weights_only=None: {},
        )

        get_warm_start_tft("lstm_demand_tft", "Staging")

        assert calls == ["Staging"]


class _FakeSessionCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc_info):
        return False


class TestTrainAndRegisterTftIncremental:
    async def test_raises_when_nothing_to_warm_start_from(self, monkeypatch):
        monkeypatch.setattr(incremental_tft, "configure_mlflow", lambda settings: None)
        monkeypatch.setattr(
            incremental_tft, "get_warm_start_tft", lambda model_name, stage: None
        )

        with pytest.raises(ValueError, match="no Production/Staging version"):
            await train_and_register_tft_incremental(
                "lstm_demand_tft", ["NSW1"], pd.Timestamp.now(tz="UTC")
            )

    async def test_raises_when_window_has_no_data(self, monkeypatch):
        warm_start = TFTWarmStart(
            run_id="run-1",
            version="3",
            stage="Production",
            state_dict={},
            hidden_size=8,
            n_heads=2,
            dropout=0.0,
            horizon=4,
            lookback=8,
        )
        monkeypatch.setattr(incremental_tft, "configure_mlflow", lambda settings: None)
        monkeypatch.setattr(
            incremental_tft, "get_warm_start_tft", lambda model_name, stage: warm_start
        )
        monkeypatch.setattr(incremental_tft, "get_session", lambda: _FakeSessionCtx())

        async def fake_load_training_data(db, regions, since=None):
            return pd.DataFrame()

        async def fake_load_holidays(db):
            return pd.DataFrame()

        monkeypatch.setattr(
            incremental_tft, "load_training_data", fake_load_training_data
        )
        monkeypatch.setattr(incremental_tft, "load_holidays", fake_load_holidays)

        with pytest.raises(ValueError, match="no training data found"):
            await train_and_register_tft_incremental(
                "lstm_demand_tft", ["NSW1"], pd.Timestamp.now(tz="UTC")
            )

    async def test_warm_starts_config_from_previous_version_and_registers(
        self, monkeypatch
    ):
        warm_start = TFTWarmStart(
            run_id="run-1",
            version="3",
            stage="Production",
            state_dict={"weight": torch.zeros(1)},
            hidden_size=8,
            n_heads=2,
            dropout=0.0,
            horizon=4,
            lookback=8,
        )
        monkeypatch.setattr(incremental_tft, "configure_mlflow", lambda settings: None)
        monkeypatch.setattr(
            incremental_tft, "get_warm_start_tft", lambda model_name, stage: warm_start
        )
        monkeypatch.setattr(incremental_tft, "get_session", lambda: _FakeSessionCtx())

        captured_since = {}

        async def fake_load_training_data(db, regions, since=None):
            captured_since["since"] = since
            return pd.DataFrame(
                {"ts": [pd.Timestamp.now(tz="UTC")], "region": ["NSW1"]}
            )

        async def fake_load_holidays(db):
            return pd.DataFrame()

        monkeypatch.setattr(
            incremental_tft, "load_training_data", fake_load_training_data
        )
        monkeypatch.setattr(incremental_tft, "load_holidays", fake_load_holidays)

        captured = {}

        class _FakeModel:
            def state_dict(self):
                return {}

        class _FakeTrainResult:
            n_train_windows = 42
            model = _FakeModel()

        fake_result = _FakeTrainResult()

        def fake_train_tft_model(
            raw_df, config, *, holidays=None, warm_start_state_dict=None
        ):
            captured["config"] = config
            captured["warm_start_state_dict"] = warm_start_state_dict
            return fake_result

        monkeypatch.setattr(incremental_tft, "train_tft_model", fake_train_tft_model)
        monkeypatch.setattr(
            incremental_tft.divergence,
            "check_drift",
            lambda state_dict, model_name: None,
        )

        def fake_log_and_register_run(
            result,
            config,
            regions,
            model_name,
            *,
            register,
            extra_tags=None,
            extra_params=None,
        ):
            captured["log_call"] = (
                result,
                config,
                regions,
                model_name,
                register,
                extra_tags,
                extra_params,
            )
            return TrainAndRegisterResult(
                run_id="run-2", model_version="4", test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            incremental_tft, "log_and_register_run", fake_log_and_register_run
        )

        since = pd.Timestamp.now(tz="UTC")
        result = await train_and_register_tft_incremental(
            "lstm_demand_tft", ["NSW1"], since
        )

        assert result.run_id == "run-2"
        assert captured_since["since"] is since
        assert captured["warm_start_state_dict"] is warm_start.state_dict
        assert captured["config"].hidden_size == 8
        assert captured["config"].n_heads == 2
        assert captured["config"].horizon == 4
        assert captured["config"].lookback == 8
        settings = get_settings()
        assert captured["config"].epochs == settings.incremental_train_epochs
        assert captured["config"].lr == settings.incremental_train_lr
        assert captured["log_call"][0] is fake_result
        assert captured["log_call"][5] == {
            "training_type": "incremental",
            "warm_start_run_id": "run-1",
            "warm_start_stage": "Production",
            "architecture": "tft",
        }
        # `check_drift` returned `None` in this test -- no drift keys at
        # all (not a misleading zero/placeholder), just the always-
        # present real encoder/decoder feature counts.
        from app.service.ml.train_tft import DECODER_COLUMNS, ENCODER_COLUMNS

        assert captured["log_call"][6] == {
            "n_encoder_features": len(ENCODER_COLUMNS),
            "n_decoder_features": len(DECODER_COLUMNS),
        }

    async def test_drift_report_is_passed_through_as_extra_params(self, monkeypatch):
        from app.service.ml.divergence import DriftReport

        warm_start = TFTWarmStart(
            run_id="run-1",
            version="3",
            stage="Production",
            state_dict={"weight": torch.zeros(1)},
            hidden_size=8,
            n_heads=2,
            dropout=0.0,
            horizon=4,
            lookback=8,
        )
        monkeypatch.setattr(incremental_tft, "configure_mlflow", lambda settings: None)
        monkeypatch.setattr(
            incremental_tft, "get_warm_start_tft", lambda model_name, stage: warm_start
        )
        monkeypatch.setattr(incremental_tft, "get_session", lambda: _FakeSessionCtx())

        async def fake_load_training_data(db, regions, since=None):
            return pd.DataFrame(
                {"ts": [pd.Timestamp.now(tz="UTC")], "region": ["NSW1"]}
            )

        async def fake_load_holidays(db):
            return pd.DataFrame()

        monkeypatch.setattr(
            incremental_tft, "load_training_data", fake_load_training_data
        )
        monkeypatch.setattr(incremental_tft, "load_holidays", fake_load_holidays)

        class _FakeModel:
            def state_dict(self):
                return {}

        class _FakeTrainResult:
            n_train_windows = 42
            model = _FakeModel()

        monkeypatch.setattr(
            incremental_tft, "train_tft_model", lambda *a, **k: _FakeTrainResult()
        )

        report = DriftReport(
            relative_l2_drift=0.9,
            exceeded_threshold=True,
            threshold=0.5,
            compared_against_run_id="anchor-1",
        )
        monkeypatch.setattr(
            incremental_tft.divergence,
            "check_drift",
            lambda state_dict, model_name: report,
        )

        captured = {}

        def fake_log_and_register_run(
            result,
            config,
            regions,
            model_name,
            *,
            register,
            extra_tags=None,
            extra_params=None,
        ):
            captured["extra_params"] = extra_params
            return TrainAndRegisterResult(
                run_id="run-2", model_version="4", test_metrics={}, final_val_mape=None
            )

        monkeypatch.setattr(
            incremental_tft, "log_and_register_run", fake_log_and_register_run
        )

        await train_and_register_tft_incremental(
            "lstm_demand_tft", ["NSW1"], pd.Timestamp.now(tz="UTC")
        )

        assert captured["extra_params"]["drift_relative_l2"] == 0.9
        assert captured["extra_params"]["drift_exceeded_threshold"] is True
        assert captured["extra_params"]["drift_compared_against_run_id"] == "anchor-1"
