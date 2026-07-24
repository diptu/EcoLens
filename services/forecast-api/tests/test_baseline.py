"""Tests for ecolens_forecast_api.forecasting.baseline.

Pure-function tests -- no I/O, no FastAPI, no database.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ecolens_forecast_api.forecasting.baseline import (
    MODEL_NAME,
    forecast_from_latest_row,
)

BASE_TS = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def _row(**overrides):
    row = {
        "ts_30": BASE_TS,
        "demand_mw": 5000.0,
        "demand_rolling_std_7d": 200.0,
    }
    # demand_lag_01..48: lag_k = 5000 - 10*k, so values are distinguishable.
    row.update({f"demand_lag_{k:02d}": 5000.0 - 10 * k for k in range(1, 49)})
    row.update(overrides)
    return row


class TestHorizonMapping:
    def test_h1_maps_to_lag_47(self):
        steps = forecast_from_latest_row(
            _row(), horizon=1, interval_minutes=30, z_score=1.2816
        )
        assert steps[0]["p50"] == _row()["demand_lag_47"]

    def test_h48_maps_to_demand_mw_itself(self):
        steps = forecast_from_latest_row(
            _row(), horizon=48, interval_minutes=30, z_score=1.2816
        )
        assert steps[-1]["p50"] == 5000.0

    def test_horizon_step_numbers_are_sequential(self):
        steps = forecast_from_latest_row(
            _row(), horizon=5, interval_minutes=30, z_score=1.2816
        )
        assert [s["horizon_step"] for s in steps] == [1, 2, 3, 4, 5]

    def test_timestamps_step_forward_by_interval(self):
        steps = forecast_from_latest_row(
            _row(), horizon=3, interval_minutes=30, z_score=1.2816
        )
        assert steps[0]["ts"] == BASE_TS.replace(minute=30)
        assert steps[1]["ts"] == BASE_TS.replace(hour=13, minute=0)
        assert steps[2]["ts"] == BASE_TS.replace(hour=13, minute=30)


class TestUncertaintyBand:
    def test_p10_p90_symmetric_around_p50(self):
        steps = forecast_from_latest_row(
            _row(), horizon=1, interval_minutes=30, z_score=1.2816
        )
        step = steps[0]
        assert step["p50"] - step["p10"] == pytest.approx(step["p90"] - step["p50"])
        assert step["p10"] == pytest.approx(step["p50"] - 1.2816 * 200.0)
        assert step["p90"] == pytest.approx(step["p50"] + 1.2816 * 200.0)

    def test_zero_std_collapses_band_to_point(self):
        steps = forecast_from_latest_row(
            _row(demand_rolling_std_7d=0.0),
            horizon=1,
            interval_minutes=30,
            z_score=1.2816,
        )
        step = steps[0]
        assert step["p10"] == step["p50"] == step["p90"]

    def test_missing_std_treated_as_zero(self):
        row = _row()
        del row["demand_rolling_std_7d"]
        steps = forecast_from_latest_row(
            row, horizon=1, interval_minutes=30, z_score=1.2816
        )
        step = steps[0]
        assert step["p10"] == step["p50"] == step["p90"]


class TestMissingLag:
    def test_null_lag_produces_null_band(self):
        row = _row()
        row["demand_lag_47"] = None
        steps = forecast_from_latest_row(
            row, horizon=1, interval_minutes=30, z_score=1.2816
        )
        step = steps[0]
        assert step["p10"] is None
        assert step["p50"] is None
        assert step["p90"] is None


class TestValidation:
    def test_horizon_zero_raises(self):
        with pytest.raises(ValueError):
            forecast_from_latest_row(
                _row(), horizon=0, interval_minutes=30, z_score=1.2816
            )

    def test_horizon_over_48_raises(self):
        with pytest.raises(ValueError):
            forecast_from_latest_row(
                _row(), horizon=49, interval_minutes=30, z_score=1.2816
            )


def test_model_name_is_labelled_as_baseline():
    assert MODEL_NAME == "seasonal_naive_v1"
