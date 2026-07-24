"""Tests for ecolens.forecasting.evaluation.metrics (ECO-114)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ecolens.forecasting.evaluation.metrics import evaluate_predictions, mae, mape, rmse


class TestPointMetrics:
    def test_mae_known_value(self):
        y_true = np.array([10.0, 20.0, 30.0])
        y_pred = np.array([12.0, 18.0, 33.0])
        assert mae(y_true, y_pred) == np.mean([2, 2, 3])

    def test_rmse_known_value(self):
        y_true = np.array([0.0, 0.0])
        y_pred = np.array([3.0, 4.0])
        assert rmse(y_true, y_pred) == np.sqrt((9 + 16) / 2)

    def test_mape_known_value(self):
        y_true = np.array([100.0, 200.0])
        y_pred = np.array([110.0, 180.0])
        assert mape(y_true, y_pred) == 10.0  # 10% and 10% off

    def test_zero_error_gives_zero_metrics(self):
        y = np.array([1.0, 2.0, 3.0])
        assert mae(y, y) == 0.0
        assert rmse(y, y) == 0.0
        assert mape(y, y) == 0.0


class TestEvaluatePredictions:
    def test_overall_and_per_horizon_shapes(self):
        rng = np.random.default_rng(0)
        y_true = rng.normal(5000, 100, size=(50, 48))
        y_pred = y_true + rng.normal(0, 10, size=(50, 48))
        report = evaluate_predictions(y_true, y_pred)
        assert set(report.overall) == {"mae", "rmse", "mape"}
        assert len(report.per_horizon_step) == 48
        assert list(report.per_horizon_step["horizon_step"]) == list(range(1, 49))

    def test_per_region_breakdown(self):
        rng = np.random.default_rng(1)
        y_true = rng.normal(5000, 100, size=(20, 4))
        y_pred = y_true.copy()
        regions = pd.Series(["NSW1"] * 10 + ["VIC1"] * 10)
        report = evaluate_predictions(y_true, y_pred, regions=regions)
        assert set(report.per_region["region"]) == {"NSW1", "VIC1"}
        assert (report.per_region["mae"] == 0).all()

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError, match="shape mismatch"):
            evaluate_predictions(np.zeros((2, 3)), np.zeros((2, 4)))
