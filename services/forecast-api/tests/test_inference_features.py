"""Tests for ecolens_forecast_api.forecasting.features (ECO-F05/F06)."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from ecolens_forecast_api.forecasting.features import (
    FEATURE_COLUMNS,
    TARGET_INDEX,
    ConformalCalibration,
    FeatureScaler,
    build_window,
)


def _row(ts_offset: int, **overrides) -> dict:
    row = {"ts_30": datetime(2026, 1, 1) + timedelta(minutes=30 * ts_offset)}
    row.update({col: 1.0 for col in FEATURE_COLUMNS})
    row.update(overrides)
    return row


class TestFeatureScaler:
    def test_transform_and_inverse_round_trip(self):
        scaler = FeatureScaler(
            mean=np.full(len(FEATURE_COLUMNS), 10.0),
            std=np.full(len(FEATURE_COLUMNS), 2.0),
            columns=FEATURE_COLUMNS,
        )
        x = np.full((1, len(FEATURE_COLUMNS)), 12.0)
        scaled = scaler.transform(x)
        assert np.allclose(scaled, 1.0)  # (12 - 10) / 2

        y_scaled = np.array([[1.0, 2.0]])
        recovered = scaler.inverse_transform_target(y_scaled)
        expected = y_scaled * 2.0 + 10.0
        assert np.allclose(recovered, expected)

    def test_from_dict(self):
        d = {"mean": [1.0, 2.0], "std": [3.0, 4.0], "columns": ["a", "b"]}
        scaler = FeatureScaler.from_dict(d)
        assert np.array_equal(scaler.mean, np.array([1.0, 2.0]))
        assert scaler.columns == ("a", "b")


class TestConformalCalibration:
    def test_calibrate_widens_symmetrically(self):
        cal = ConformalCalibration(q_hat=np.array([5.0, 10.0]), alpha=0.1)
        p10 = np.array([[100.0, 200.0]])
        p90 = np.array([[110.0, 220.0]])
        cal_p10, cal_p90 = cal.calibrate(p10, p90)
        assert np.allclose(cal_p10, [[95.0, 190.0]])
        assert np.allclose(cal_p90, [[115.0, 230.0]])

    def test_from_dict(self):
        cal = ConformalCalibration.from_dict({"q_hat": [1.0, 2.0], "alpha": 0.2})
        assert np.array_equal(cal.q_hat, np.array([1.0, 2.0]))
        assert cal.alpha == 0.2


class TestBuildWindow:
    def test_uses_most_recent_lookback_rows_in_order(self):
        rows = [_row(i, demand_mw=float(i)) for i in range(60)]
        scaler = FeatureScaler(
            mean=np.zeros(len(FEATURE_COLUMNS)),
            std=np.ones(len(FEATURE_COLUMNS)),
            columns=FEATURE_COLUMNS,
        )
        window = build_window(rows, lookback=48, scaler=scaler)
        assert window.shape == (1, 48, len(FEATURE_COLUMNS))
        demand_idx = FEATURE_COLUMNS.index("demand_mw")
        # Last 48 rows are indices 12..59 -- demand_mw should be ascending 12..59.
        assert window[0, 0, demand_idx] == 12.0
        assert window[0, -1, demand_idx] == 59.0

    def test_raises_when_not_enough_rows(self):
        rows = [_row(i) for i in range(10)]
        scaler = FeatureScaler(
            mean=np.zeros(len(FEATURE_COLUMNS)),
            std=np.ones(len(FEATURE_COLUMNS)),
            columns=FEATURE_COLUMNS,
        )
        with pytest.raises(ValueError, match="need at least"):
            build_window(rows, lookback=48, scaler=scaler)

    def test_target_index_matches_demand_mw(self):
        assert FEATURE_COLUMNS[TARGET_INDEX] == "demand_mw"
