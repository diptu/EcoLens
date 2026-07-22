"""Tests for ecolens_forecast_api.forecasting.lstm_forecast (ECO-F06)."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from ecolens_forecast_api.forecasting.features import (
    FEATURE_COLUMNS,
    ConformalCalibration,
    FeatureScaler,
)
from ecolens_forecast_api.forecasting.loader import LoadedModel
from ecolens_forecast_api.forecasting.lstm_forecast import (
    forecast_from_recent_rows,
    model_name,
)
from ecolens_forecast_api.forecasting.model import DemandLSTM


def _rows(n: int) -> list[dict]:
    rows = []
    for i in range(n):
        row = {"ts_30": datetime(2026, 1, 1, i // 2, 30 * (i % 2))}
        row.update({col: 0.0 for col in FEATURE_COLUMNS})
        rows.append(row)
    return rows


def _model_and_scaler() -> tuple[DemandLSTM, FeatureScaler]:
    model = DemandLSTM(
        n_features=len(FEATURE_COLUMNS), hidden_size=8, num_layers=1, horizon=48
    )
    model.eval()
    scaler = FeatureScaler(
        mean=np.zeros(len(FEATURE_COLUMNS)),
        std=np.ones(len(FEATURE_COLUMNS)),
        columns=FEATURE_COLUMNS,
    )
    return model, scaler


def _loaded_model(
    model: DemandLSTM,
    scaler: FeatureScaler,
    *,
    calibration: ConformalCalibration | None = None,
) -> LoadedModel:
    return LoadedModel(
        model=model,
        scaler=scaler,
        calibration=calibration,
        version="3",
        run_id="abc123",
    )


class TestModelName:
    def test_includes_version(self):
        model, scaler = _model_and_scaler()
        assert model_name(_loaded_model(model, scaler)) == "demand_lstm_v3"


class TestForecastFromRecentRows:
    def test_returns_horizon_steps_with_correct_timestamps(self):
        model, scaler = _model_and_scaler()
        rows = _rows(48)
        steps = forecast_from_recent_rows(
            _loaded_model(model, scaler),
            rows,
            lookback=48,
            horizon=48,
            interval_minutes=30,
        )
        assert len(steps) == 48
        assert steps[0]["horizon_step"] == 1
        assert steps[-1]["horizon_step"] == 48

        base_ts = rows[-1]["ts_30"]
        assert steps[0]["ts"] == base_ts + timedelta(minutes=30)
        assert steps[-1]["ts"] == base_ts + timedelta(minutes=30 * 48)
        for key in ("p10", "p50", "p90"):
            assert isinstance(steps[0][key], float)

    def test_respects_horizon_shorter_than_model_output(self):
        model, scaler = _model_and_scaler()
        rows = _rows(48)
        steps = forecast_from_recent_rows(
            _loaded_model(model, scaler),
            rows,
            lookback=48,
            horizon=5,
            interval_minutes=30,
        )
        assert len(steps) == 5

    def test_calibration_widens_the_band(self):
        # Same model + scaler for both calls -- isolates calibration's
        # effect instead of also picking up two different random inits.
        model, scaler = _model_and_scaler()
        rows = _rows(48)

        uncalibrated = forecast_from_recent_rows(
            _loaded_model(model, scaler),
            rows,
            lookback=48,
            horizon=48,
            interval_minutes=30,
        )
        calibration = ConformalCalibration(q_hat=np.full(48, 1000.0), alpha=0.1)
        calibrated = forecast_from_recent_rows(
            _loaded_model(model, scaler, calibration=calibration),
            rows,
            lookback=48,
            horizon=48,
            interval_minutes=30,
        )

        for u, c in zip(uncalibrated, calibrated, strict=True):
            assert c["p10"] == pytest.approx(u["p10"] - 1000.0, rel=1e-4)
            assert c["p90"] == pytest.approx(u["p90"] + 1000.0, rel=1e-4)
            assert c["p50"] == pytest.approx(
                u["p50"], rel=1e-4
            )  # calibration never touches p50
