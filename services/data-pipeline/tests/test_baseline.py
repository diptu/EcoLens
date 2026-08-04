from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.models.baseline import seasonal_naive_forecast


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2026-01-01", periods=len(values), freq="5min", tz="UTC")
    return pd.Series(values, index=idx)


def test_returns_one_row_per_horizon_step():
    history = _series([float(i) for i in range(500)])

    forecast = seasonal_naive_forecast(
        history, horizon=6, period_steps=100, n_periods=3
    )

    assert list(forecast["step"]) == [1, 2, 3, 4, 5, 6]


def test_p10_le_p50_le_p90():
    rng = np.random.default_rng(42)
    history = _series(list(rng.normal(loc=100, scale=10, size=1000)))

    forecast = seasonal_naive_forecast(
        history, horizon=10, period_steps=50, n_periods=8
    )

    assert (forecast["p10"] <= forecast["p50"]).all()
    assert (forecast["p50"] <= forecast["p90"]).all()


def test_picks_the_same_point_in_the_cycle():
    # period_steps=10: value at index i repeats every 10 rows -- a
    # perfectly seasonal series, so the naive forecast should recover
    # it exactly regardless of which of the n_periods occurrences it draws from.
    values = [float(i % 10) for i in range(200)]
    history = _series(values)

    forecast = seasonal_naive_forecast(history, horizon=5, period_steps=10, n_periods=4)

    # history's last index is 199 (value 9); step=1 should land on the
    # same phase as index 190, 180, 170, 160 -> all value 0.
    assert forecast.loc[forecast["step"] == 1, "p50"].iloc[0] == 0.0


def test_nan_when_not_enough_history_for_any_period():
    history = _series([1.0, 2.0, 3.0])

    forecast = seasonal_naive_forecast(
        history, horizon=2, period_steps=1000, n_periods=4
    )

    assert forecast["p50"].isna().all()


def test_rejects_non_positive_period_or_n_periods():
    history = _series([1.0, 2.0, 3.0])

    with pytest.raises(ValueError):
        seasonal_naive_forecast(history, horizon=1, period_steps=0, n_periods=1)

    with pytest.raises(ValueError):
        seasonal_naive_forecast(history, horizon=1, period_steps=1, n_periods=0)
