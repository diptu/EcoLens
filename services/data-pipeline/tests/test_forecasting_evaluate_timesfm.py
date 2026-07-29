"""Tests for ecolens.forecasting.service.evaluation.evaluate_timesfm. Uses
the same fake `TimesFMBackbone` as test_forecasting_train_timesfm.py --
no real download/inference here either.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ecolens.config import Settings
from ecolens.forecasting.schema.features import FEATURE_COLUMNS
from ecolens.forecasting.service.evaluation.evaluate_timesfm import (
    evaluate_timesfm_model,
)
from ecolens.forecasting.service.training.train_timesfm import train_timesfm_model
from ecolens.forecasting.service.windowing import build_windowed_dataset


class _FakeBackbone:
    def forecast_raw(self, contexts, *, horizon):
        last = contexts[:, -1:]
        p50 = np.repeat(last, horizon, axis=1)
        return p50 - 200.0, p50, p50 + 200.0


def _snapshot(
    *, n: int = 400, seed: int = 0, regions=("NSW1", "QLD1", "VIC1")
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    for i, region in enumerate(regions):
        ts = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
        df = pd.DataFrame({"ts_30": ts, "region": region})
        t = np.arange(n)
        df["demand_mw"] = (
            5000 + 1000 * i + 500 * np.sin(2 * np.pi * t / 48) + rng.normal(0, 20, n)
        )
        for col in FEATURE_COLUMNS:
            if col == "demand_mw":
                continue
            df[col] = (
                rng.integers(0, 2, size=n)
                if col == "is_holiday"
                else rng.normal(size=n)
            )
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


class TestEvaluateTimesFMModel:
    def test_produces_finite_metrics_and_shape_matching_coverage(self):
        ds = build_windowed_dataset(_snapshot(), lookback=48, horizon=48)
        settings = Settings(  # type: ignore[call-arg]
            model_timesfm_train_epochs=3,
            model_timesfm_hidden_dim=16,
            model_timesfm_static_dim=8,
            model_timesfm_batch_size=32,
        )
        result = train_timesfm_model(
            ds, settings=settings, backbone=_FakeBackbone(), log_to_mlflow=False
        )

        evaluation = evaluate_timesfm_model(
            result.model, ds, result.region_to_idx, result.raw_forecasts, alpha=0.1
        )

        assert np.isfinite(evaluation.point.overall["mae"])
        assert np.isfinite(evaluation.point.overall["rmse"])
        assert np.isfinite(evaluation.point.overall["mape"])
        assert evaluation.conformal.q_hat.shape == (ds.horizon,)
        assert 0.0 <= evaluation.test_coverage <= 1.0

    def test_per_region_breakdown_covers_every_test_region(self):
        ds = build_windowed_dataset(_snapshot(), lookback=48, horizon=48)
        settings = Settings(  # type: ignore[call-arg]
            model_timesfm_train_epochs=1,
            model_timesfm_hidden_dim=8,
            model_timesfm_static_dim=8,
            model_timesfm_batch_size=32,
        )
        result = train_timesfm_model(
            ds, settings=settings, backbone=_FakeBackbone(), log_to_mlflow=False
        )
        evaluation = evaluate_timesfm_model(
            result.model, ds, result.region_to_idx, result.raw_forecasts, alpha=0.1
        )

        assert set(evaluation.point.per_region["region"]) == set(
            ds.test.region.unique()
        )
