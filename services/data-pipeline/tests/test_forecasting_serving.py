"""Tests for ecolens.forecasting.serving.forecast (ECO-117)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ecolens.forecasting.evaluation.conformal import ConformalCalibration
from ecolens.forecasting.features import FEATURE_COLUMNS, FeatureScaler
from ecolens.forecasting.models.lstm import DemandLSTM
from ecolens.forecasting.serving.forecast import batch_forecast, build_window


def _scaler() -> FeatureScaler:
    return FeatureScaler(
        mean=np.zeros(len(FEATURE_COLUMNS)),
        std=np.ones(len(FEATURE_COLUMNS)),
        columns=FEATURE_COLUMNS,
    )


def _region_df(region: str, n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    df = pd.DataFrame({"ts_30": ts, "region": region})
    for col in FEATURE_COLUMNS:
        df[col] = rng.normal(5000 if col == "demand_mw" else 0, 1, n)
    return df


class TestBuildWindow:
    def test_uses_the_most_recent_lookback_rows(self):
        df = _region_df("NSW1", n=60, seed=0)
        x, as_of = build_window(df, lookback=48, scaler=_scaler())
        assert x.shape == (1, 48, len(FEATURE_COLUMNS))
        assert as_of == df["ts_30"].iloc[-1]

    def test_raises_if_not_enough_history(self):
        df = _region_df("NSW1", n=10, seed=0)
        with pytest.raises(ValueError, match="need at least"):
            build_window(df, lookback=48, scaler=_scaler())


class TestBatchForecast:
    def test_one_forecast_per_region(self):
        df = pd.concat(
            [_region_df("NSW1", 60, 0), _region_df("VIC1", 60, 1)], ignore_index=True
        )
        model = DemandLSTM(
            n_features=len(FEATURE_COLUMNS), hidden_size=8, num_layers=1, horizon=48
        )
        results = batch_forecast(df, model=model, scaler=_scaler(), lookback=48)

        assert {r.region for r in results} == {"NSW1", "VIC1"}
        for r in results:
            assert r.p50.shape == (48,)
            assert r.p10.shape == (48,)
            assert r.p90.shape == (48,)

    def test_conformal_calibration_widens_the_band(self):
        df = _region_df("NSW1", 60, 2)
        model = DemandLSTM(
            n_features=len(FEATURE_COLUMNS), hidden_size=8, num_layers=1, horizon=48
        )
        scaler = _scaler()

        uncalibrated = batch_forecast(df, model=model, scaler=scaler, lookback=48)[0]
        calibration = ConformalCalibration(q_hat=np.full(48, 500.0), alpha=0.1)
        calibrated = batch_forecast(
            df, model=model, scaler=scaler, lookback=48, calibration=calibration
        )[0]

        assert np.allclose(calibrated.p10, uncalibrated.p10 - 500.0)
        assert np.allclose(calibrated.p90, uncalibrated.p90 + 500.0)
