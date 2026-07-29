"""Tests for ecolens.forecasting.service.evaluation.evaluate_tft.

There's no equivalent standalone test_forecasting_evaluate.py for the
LSTM's evaluate.py either -- that path is exercised via
test_forecasting_registry.py's/test_forecasting_cli.py's integration
tests. Same approach here: train briefly, then check evaluate_tft_model's
output shape/sanity, reusing the already-tested conformal/metrics modules
underneath (see test_forecasting_conformal.py for their own direct
coverage).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ecolens.forecasting.schema.features import FEATURE_COLUMNS
from ecolens.forecasting.service.evaluation.evaluate_tft import evaluate_tft_model
from ecolens.forecasting.service.training.train_tft import train_tft_model
from ecolens.forecasting.service.windowing import build_windowed_dataset

from ecolens.config import Settings


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


class TestEvaluateTFTModel:
    def test_produces_finite_metrics_and_shape_matching_coverage(self):
        ds = build_windowed_dataset(_snapshot(), lookback=48, horizon=48)
        settings = Settings(  # type: ignore[call-arg]
            model_tft_train_epochs=3,
            model_tft_d_model=16,
            model_tft_num_heads=2,
            model_tft_static_dim=8,
            model_tft_batch_size=32,
        )
        result = train_tft_model(ds, settings=settings, log_to_mlflow=False)

        evaluation = evaluate_tft_model(
            result.model, ds, result.region_to_idx, alpha=0.1
        )

        assert np.isfinite(evaluation.point.overall["mae"])
        assert np.isfinite(evaluation.point.overall["rmse"])
        assert np.isfinite(evaluation.point.overall["mape"])
        assert evaluation.conformal.q_hat.shape == (ds.horizon,)
        assert 0.0 <= evaluation.test_coverage <= 1.0

    def test_per_region_breakdown_covers_every_test_region(self):
        ds = build_windowed_dataset(_snapshot(), lookback=48, horizon=48)
        settings = Settings(  # type: ignore[call-arg]
            model_tft_train_epochs=1,
            model_tft_d_model=8,
            model_tft_num_heads=2,
            model_tft_static_dim=8,
            model_tft_batch_size=32,
        )
        result = train_tft_model(ds, settings=settings, log_to_mlflow=False)
        evaluation = evaluate_tft_model(
            result.model, ds, result.region_to_idx, alpha=0.1
        )

        assert set(evaluation.point.per_region["region"]) == set(
            ds.test.region.unique()
        )
