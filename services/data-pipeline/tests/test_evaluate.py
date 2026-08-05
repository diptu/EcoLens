from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler

from app.models.ml import DemandLSTM
from app.models.tft import DemandTFT
from app.service.ml import evaluate
from app.service.ml.conformal import ConformalCalibration
from app.service.ml.evaluate import (
    BaselineForecaster,
    LSTMForecaster,
    TFTForecaster,
    _infer_period_steps,
    evaluate_walk_forward,
    load_registered_model,
    load_registered_tft_model,
)
from app.service.ml.features import (
    FEATURE_COLUMNS,
    NUMERIC_COLUMNS,
    TARGET_COLUMN,
    build_features,
)
from app.service.ml.train_tft import DECODER_COLUMNS, ENCODER_COLUMNS


def _synthetic_region_df(
    n: int = 400, region: str = "NSW1", freq: str = "5min"
) -> pd.DataFrame:
    """A daily sine-wave demand pattern plus small noise -- same shape
    `test_train.py`'s `_synthetic_demand_df` uses, real enough that a
    seasonal-naive baseline scores meaningfully better than chance."""
    rng = np.random.default_rng(11)
    ts = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    t = np.arange(n)
    demand = 5000 + 1000 * np.sin(2 * np.pi * t / 288) + rng.normal(0, 20, n)
    temp = 20 + 5 * np.sin(2 * np.pi * t / 288)
    return pd.DataFrame(
        {
            "ts": ts,
            "region": region,
            "demand_mw": demand,
            "price_mwh": 50 + rng.normal(0, 2, n),
            "total_generation_mw": demand * 1.1,
            "total_renewable_mw": demand * 0.3,
            "temp_c": temp,
            "apparent_temp_c": temp + 1,
            "humidity_pct": np.full(n, 50.0),
            "wind_speed_kmh": np.full(n, 10.0),
        }
    )


class TestInferPeriodSteps:
    def test_infers_daily_steps_from_5_minute_cadence(self):
        df = _synthetic_region_df(n=50, freq="5min")

        assert _infer_period_steps(df) == 288

    def test_infers_daily_steps_from_30_minute_cadence(self):
        df = _synthetic_region_df(n=50, freq="30min")

        assert _infer_period_steps(df) == 48

    def test_raises_with_fewer_than_2_timestamps(self):
        df = _synthetic_region_df(n=1, freq="5min")

        with pytest.raises(ValueError):
            _infer_period_steps(df)


class TestBaselineForecaster:
    def test_predict_returns_horizon_shaped_p10_p50_p90(self):
        raw = _synthetic_region_df(n=400)
        engineered = build_features(raw)
        forecaster = BaselineForecaster(period_steps=288, n_periods=3)

        p10, p50, p90 = forecaster.predict(engineered, horizon=6)

        assert p10.shape == p50.shape == p90.shape == (6,)
        assert forecaster.name == "seasonal_naive"


class TestLSTMForecaster:
    def _build_forecaster(
        self, *, horizon: int = 4, lookback: int = 8, calibration=None
    ) -> tuple[LSTMForecaster, pd.DataFrame]:
        raw = _synthetic_region_df(n=200)
        engineered = build_features(raw)
        model = DemandLSTM(
            n_features=len(FEATURE_COLUMNS),
            horizon=horizon,
            hidden_size=8,
            num_layers=1,
        )
        feature_scaler = StandardScaler()
        clean = engineered[list(NUMERIC_COLUMNS)].dropna()
        feature_scaler.fit(clean.to_numpy())
        target_scaler = StandardScaler()
        target_scaler.fit(engineered[[TARGET_COLUMN]].dropna().to_numpy())

        forecaster = LSTMForecaster(
            model=model,
            feature_scalers={"NSW1": feature_scaler},
            target_scaler=target_scaler,
            lookback=lookback,
            calibration=calibration,
        )
        return forecaster, engineered

    def test_predict_returns_horizon_shaped_output(self):
        forecaster, engineered = self._build_forecaster(horizon=4, lookback=8)

        p10, p50, p90 = forecaster.predict(engineered, horizon=4)

        assert p10.shape == p50.shape == p90.shape == (4,)
        assert not np.isnan(p50).any()

    def test_predict_returns_nan_when_history_shorter_than_lookback(self):
        forecaster, engineered = self._build_forecaster(horizon=4, lookback=8)
        short_history = engineered.iloc[:3]

        p10, p50, p90 = forecaster.predict(short_history, horizon=4)

        assert np.isnan(p50).all()

    def test_predict_returns_nan_for_unknown_region(self):
        forecaster, engineered = self._build_forecaster(horizon=4, lookback=8)
        other_region = engineered.copy()
        other_region["region"] = "QLD1"

        p10, p50, p90 = forecaster.predict(other_region, horizon=4)

        assert np.isnan(p50).all()

    def test_predict_raises_on_horizon_mismatch(self):
        forecaster, engineered = self._build_forecaster(horizon=4, lookback=8)

        with pytest.raises(ValueError):
            forecaster.predict(engineered, horizon=6)

    def test_calibration_widens_the_interval(self):
        calibration = ConformalCalibration(q=np.full(4, 50.0), alpha=0.2)
        forecaster_raw, engineered = self._build_forecaster(
            horizon=4, lookback=8, calibration=None
        )
        forecaster_cal, _ = self._build_forecaster(
            horizon=4, lookback=8, calibration=calibration
        )
        # Both forecasters wrap independently constructed (randomly
        # initialized) models, so compare each against its own raw
        # output rather than cross-model -- what matters here is only
        # that calibration widens by exactly `q`.
        forecaster_cal.model.load_state_dict(forecaster_raw.model.state_dict())

        p10_raw, _, p90_raw = forecaster_raw.predict(engineered, horizon=4)
        p10_cal, _, p90_cal = forecaster_cal.predict(engineered, horizon=4)

        assert np.allclose(p10_cal, p10_raw - 50.0)
        assert np.allclose(p90_cal, p90_raw + 50.0)


class TestEvaluateWalkForward:
    def test_scores_multiple_origins_against_the_baseline(self):
        raw = _synthetic_region_df(n=400)
        engineered = build_features(raw)
        forecaster = BaselineForecaster(period_steps=288, n_periods=3)

        report = evaluate_walk_forward(
            forecaster, engineered, horizon=6, n_origins=5, min_history=289
        )

        assert report.n_origins > 0
        assert report.n_origins <= 5
        assert not np.isnan(report.mape)
        assert 0.0 <= report.empirical_coverage <= 1.0
        assert report.pinball_loss_50 >= 0.0

    def test_returns_zero_origins_report_when_window_too_short(self):
        raw = _synthetic_region_df(n=20)
        engineered = build_features(raw)
        forecaster = BaselineForecaster(period_steps=288, n_periods=3)

        report = evaluate_walk_forward(
            forecaster, engineered, horizon=6, n_origins=5, min_history=289
        )

        assert report.n_origins == 0
        assert np.isnan(report.mape)
        assert np.isnan(report.empirical_coverage)

    def test_as_mlflow_metrics_has_the_expected_keys(self):
        raw = _synthetic_region_df(n=400)
        engineered = build_features(raw)
        forecaster = BaselineForecaster(period_steps=288, n_periods=3)

        report = evaluate_walk_forward(
            forecaster, engineered, horizon=6, n_origins=3, min_history=289
        )
        metrics = report.as_mlflow_metrics()

        assert set(metrics) == {
            "eval_mape",
            "eval_rmse",
            "eval_pinball_p10",
            "eval_pinball_p50",
            "eval_pinball_p90",
            "eval_coverage",
            "eval_n_origins",
        }


class _FakeVersion:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id


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

    def get_model_version(self, name: str, version: str) -> _FakeVersion:
        return _FakeVersion(self._run_id)

    def get_run(self, run_id: str) -> _FakeRun:
        assert run_id == self._run_id
        return _FakeRun(self._params)


_FAKE_PARAMS = {
    "hidden_size": "8",
    "num_layers": "1",
    "dropout": "0.0",
    "horizon": "4",
    "lookback": "8",
}


class TestLoadRegisteredModel:
    def test_loads_weights_scalers_and_calibration(self, monkeypatch):
        state_dict = DemandLSTM(
            n_features=len(FEATURE_COLUMNS), horizon=4, hidden_size=8, num_layers=1
        ).state_dict()
        feature_scalers = {
            "NSW1": StandardScaler().fit(np.zeros((2, len(NUMERIC_COLUMNS))))
        }
        target_scaler = StandardScaler().fit(np.zeros((2, 1)))

        monkeypatch.setattr(
            evaluate, "MlflowClient", lambda: _FakeMlflowClient("run-1", _FAKE_PARAMS)
        )
        monkeypatch.setattr(
            evaluate.mlflow.artifacts,
            "download_artifacts",
            lambda **kwargs: "/fake/dir",
        )
        monkeypatch.setattr(
            evaluate.torch,
            "load",
            lambda path, map_location=None, weights_only=None: state_dict,
        )

        def fake_joblib_load(path):
            name = str(path)
            if "feature_scalers" in name:
                return feature_scalers
            if "target_scaler" in name:
                return target_scaler
            raise AssertionError(f"unexpected joblib.load path: {name}")

        monkeypatch.setattr(evaluate.joblib, "load", fake_joblib_load)
        monkeypatch.setattr(
            evaluate.mlflow.artifacts,
            "load_dict",
            lambda uri: {"q": [1.0, 2.0, 3.0, 4.0], "alpha": 0.2},
        )

        forecaster = load_registered_model("lstm_demand", 1)

        assert forecaster.lookback == 8
        assert forecaster.model.horizon == 4
        assert forecaster.calibration is not None
        assert forecaster.calibration.q.tolist() == [1.0, 2.0, 3.0, 4.0]
        assert forecaster.name == "lstm_demand_v1"

    def test_missing_calibration_artifact_falls_back_to_none(self, monkeypatch):
        state_dict = DemandLSTM(
            n_features=len(FEATURE_COLUMNS), horizon=4, hidden_size=8, num_layers=1
        ).state_dict()

        monkeypatch.setattr(
            evaluate, "MlflowClient", lambda: _FakeMlflowClient("run-1", _FAKE_PARAMS)
        )
        monkeypatch.setattr(
            evaluate.mlflow.artifacts,
            "download_artifacts",
            lambda **kwargs: "/fake/dir",
        )
        monkeypatch.setattr(
            evaluate.torch,
            "load",
            lambda path, map_location=None, weights_only=None: state_dict,
        )
        monkeypatch.setattr(
            evaluate.joblib,
            "load",
            lambda path: {"NSW1": StandardScaler().fit(np.zeros((2, 1)))},
        )

        def raise_missing(uri):
            raise OSError("no such artifact")

        monkeypatch.setattr(evaluate.mlflow.artifacts, "load_dict", raise_missing)

        forecaster = load_registered_model("lstm_demand", 1)

        assert forecaster.calibration is None


class TestTFTForecaster:
    def _build_forecaster(
        self, *, horizon: int = 4, lookback: int = 8, calibration=None
    ) -> tuple[TFTForecaster, "pd.DataFrame"]:
        raw = _synthetic_region_df(n=200)
        engineered = build_features(raw)
        model = DemandTFT(
            n_encoder_features=len(ENCODER_COLUMNS),
            n_decoder_features=len(DECODER_COLUMNS),
            horizon=horizon,
            hidden_size=8,
            n_heads=2,
        )
        feature_scaler = StandardScaler()
        clean = engineered[list(NUMERIC_COLUMNS)].dropna()
        feature_scaler.fit(clean.to_numpy())
        target_scaler = StandardScaler()
        target_scaler.fit(engineered[[TARGET_COLUMN]].dropna().to_numpy())

        forecaster = TFTForecaster(
            model=model,
            feature_scalers={"NSW1": feature_scaler},
            target_scaler=target_scaler,
            lookback=lookback,
            calibration=calibration,
        )
        return forecaster, engineered

    def test_predict_returns_horizon_shaped_output(self):
        forecaster, engineered = self._build_forecaster(horizon=4, lookback=8)

        p10, p50, p90 = forecaster.predict(engineered, horizon=4)

        assert p10.shape == p50.shape == p90.shape == (4,)
        assert not np.isnan(p50).any()

    def test_predict_returns_nan_when_history_shorter_than_lookback(self):
        forecaster, engineered = self._build_forecaster(horizon=4, lookback=8)
        short_history = engineered.iloc[:3]

        p10, p50, p90 = forecaster.predict(short_history, horizon=4)

        assert np.isnan(p50).all()

    def test_predict_returns_nan_for_unknown_region(self):
        forecaster, engineered = self._build_forecaster(horizon=4, lookback=8)
        other_region = engineered.copy()
        other_region["region"] = "QLD1"

        p10, p50, p90 = forecaster.predict(other_region, horizon=4)

        assert np.isnan(p50).all()

    def test_predict_raises_on_horizon_mismatch(self):
        forecaster, engineered = self._build_forecaster(horizon=4, lookback=8)

        with pytest.raises(ValueError):
            forecaster.predict(engineered, horizon=6)

    def test_decoder_inputs_extend_the_real_cadence_past_the_last_history_row(self):
        forecaster, engineered = self._build_forecaster(horizon=3, lookback=8)
        window = engineered.iloc[-8:]
        last_ts = window["ts"].iloc[-1]
        step = window["ts"].diff().dropna().median()

        captured = {}
        original_forward = forecaster.model.forward

        def spy_forward(x_encoder, x_decoder):
            captured["x_decoder"] = x_decoder
            return original_forward(x_encoder, x_decoder)

        forecaster.model.forward = spy_forward
        forecaster.predict(engineered, horizon=3)

        # Independently compute what the first future step's hour_sin
        # *should* be (a pure function of `last_ts + step`), and confirm
        # the synthesized decoder input matches exactly -- a real,
        # deterministic check that this is genuinely the next real
        # timestamp's calendar encoding, not a copy of the last observed
        # row or some other placeholder.
        expected_first_future_ts = last_ts + step
        expected_hour_sin = np.sin(2 * np.pi * expected_first_future_ts.hour / 24)

        assert "x_decoder" in captured
        assert captured["x_decoder"].shape == (1, 3, len(DECODER_COLUMNS))
        future_hour_sin = captured["x_decoder"][
            0, 0, DECODER_COLUMNS.index("hour_sin")
        ].item()
        assert future_hour_sin == pytest.approx(expected_hour_sin, abs=1e-5)


class _FakeTftVersion:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id


class _FakeTftRunData:
    def __init__(self, params: dict[str, str]) -> None:
        self.params = params


class _FakeTftRun:
    def __init__(self, params: dict[str, str]) -> None:
        self.data = _FakeTftRunData(params)


class _FakeTftMlflowClient:
    def __init__(self, run_id: str, params: dict[str, str]) -> None:
        self._run_id = run_id
        self._params = params

    def get_model_version(self, name: str, version: str) -> _FakeTftVersion:
        return _FakeTftVersion(self._run_id)

    def get_run(self, run_id: str) -> _FakeTftRun:
        assert run_id == self._run_id
        return _FakeTftRun(self._params)


_FAKE_TFT_PARAMS = {
    "hidden_size": "8",
    "n_heads": "2",
    "dropout": "0.0",
    "horizon": "4",
    "lookback": "8",
    "n_encoder_features": str(len(ENCODER_COLUMNS)),
    "n_decoder_features": str(len(DECODER_COLUMNS)),
}


class TestLoadRegisteredTftModel:
    def test_loads_weights_scalers_and_calibration(self, monkeypatch):
        state_dict = DemandTFT(
            n_encoder_features=len(ENCODER_COLUMNS),
            n_decoder_features=len(DECODER_COLUMNS),
            horizon=4,
            hidden_size=8,
            n_heads=2,
        ).state_dict()
        feature_scalers = {
            "NSW1": StandardScaler().fit(np.zeros((2, len(NUMERIC_COLUMNS))))
        }
        target_scaler = StandardScaler().fit(np.zeros((2, 1)))

        monkeypatch.setattr(
            evaluate,
            "MlflowClient",
            lambda: _FakeTftMlflowClient("run-1", _FAKE_TFT_PARAMS),
        )
        monkeypatch.setattr(
            evaluate.mlflow.artifacts,
            "download_artifacts",
            lambda **kwargs: "/fake/dir",
        )
        monkeypatch.setattr(
            evaluate.torch,
            "load",
            lambda path, map_location=None, weights_only=None: state_dict,
        )

        def fake_joblib_load(path):
            name = str(path)
            if "feature_scalers" in name:
                return feature_scalers
            if "target_scaler" in name:
                return target_scaler
            raise AssertionError(f"unexpected joblib.load path: {name}")

        monkeypatch.setattr(evaluate.joblib, "load", fake_joblib_load)
        monkeypatch.setattr(
            evaluate.mlflow.artifacts,
            "load_dict",
            lambda uri: {"q": [1.0, 2.0, 3.0, 4.0], "alpha": 0.2},
        )

        forecaster = load_registered_tft_model("lstm_demand_tft", 1)

        assert forecaster.lookback == 8
        assert forecaster.model.horizon == 4
        assert forecaster.calibration is not None
        assert forecaster.name == "lstm_demand_tft_v1"
