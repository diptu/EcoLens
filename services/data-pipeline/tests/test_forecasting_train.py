"""Tests for ecolens.forecasting.training.train (ECO-112).

All of these use `log_to_mlflow=False` -- MLflow logging itself is
covered by `test_forecasting_registry.py`'s integration tests against a
real local tracking store; these focus on the training mechanics
(loss decreasing, early stopping, checkpoint selection) in isolation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from ecolens.config import Settings
from ecolens.forecasting.features import FEATURE_COLUMNS, build_windowed_dataset
from ecolens.forecasting.training.losses import DemandForecastLoss
from ecolens.forecasting.training.train import train_model


def _learnable_snapshot(*, n: int = 400, seed: int = 0) -> pd.DataFrame:
    """A demand series with a genuine learnable diurnal pattern (not
    pure noise), so a trained model should measurably beat a fresh one.
    """
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    df = pd.DataFrame({"ts_30": ts, "region": "NSW1"})
    t = np.arange(n)
    df["demand_mw"] = 5000 + 500 * np.sin(2 * np.pi * t / 48) + rng.normal(0, 20, n)
    for col in FEATURE_COLUMNS:
        if col == "demand_mw":
            continue
        df[col] = (
            rng.integers(0, 2, size=n)
            if col in ("is_holiday", "is_weekend")
            else rng.normal(size=n)
        )
    return df


class TestTrainModel:
    def test_loss_decreases_over_training(self):
        ds = build_windowed_dataset(_learnable_snapshot(), lookback=48, horizon=48)
        settings = Settings(  # type: ignore[call-arg]
            model_train_epochs=10,
            model_hidden_size=16,
            model_num_layers=1,
            model_batch_size=32,
            model_early_stop_patience=10,
        )
        result = train_model(ds, settings=settings, log_to_mlflow=False)
        assert result.epochs_trained == 10
        assert (
            result.best_val_loss < 0.9
        )  # meaningfully below a freshly-initialized model's loss

    def test_early_stopping_triggers(self):
        ds = build_windowed_dataset(
            _learnable_snapshot(seed=1), lookback=48, horizon=48
        )
        settings = Settings(  # type: ignore[call-arg]
            model_train_epochs=100,
            model_hidden_size=32,
            model_num_layers=1,
            model_train_lr=0.05,  # aggressive LR to overfit/plateau fast
            model_batch_size=32,
            model_early_stop_patience=2,
        )
        result = train_model(ds, settings=settings, log_to_mlflow=False)
        assert result.epochs_trained < 100

    def test_returned_model_is_the_best_checkpoint_not_the_last(self):
        # With a high LR and low patience, the best epoch is very likely
        # not the final one -- and train_model must restore it before
        # returning, not leave the model at whatever the loop last did.
        ds = build_windowed_dataset(
            _learnable_snapshot(seed=2), lookback=48, horizon=48
        )
        settings = Settings(  # type: ignore[call-arg]
            model_train_epochs=30,
            model_hidden_size=32,
            model_train_lr=0.05,
            model_batch_size=32,
            model_early_stop_patience=3,
        )
        result = train_model(ds, settings=settings, log_to_mlflow=False)

        loss_fn = DemandForecastLoss()
        with torch.no_grad():
            outputs, _ = result.model(ds.val.x)
            actual_loss, _ = loss_fn(outputs, ds.val.y)
        assert actual_loss.item() == pytest.approx(result.best_val_loss, rel=1e-3)
