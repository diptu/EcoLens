"""Tests for ecolens.forecasting.training.online (ECO-118)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from ecolens.config import Settings
from ecolens.forecasting.features import FEATURE_COLUMNS, build_windowed_dataset
from ecolens.forecasting.models.lstm import DemandLSTM
from ecolens.forecasting.training.online import fine_tune


def _dataset():
    rng = np.random.default_rng(7)
    n = 300
    ts = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    df = pd.DataFrame({"ts_30": ts, "region": "NSW1"})
    t = np.arange(n)
    df["demand_mw"] = 5000 + 400 * np.sin(2 * np.pi * t / 48) + rng.normal(0, 20, n)
    for col in FEATURE_COLUMNS:
        if col == "demand_mw":
            continue
        df[col] = (
            rng.integers(0, 2, size=n)
            if col in ("is_holiday", "is_weekend")
            else rng.normal(size=n)
        )
    return build_windowed_dataset(df, lookback=48, horizon=48)


class TestFineTune:
    def test_does_not_mutate_the_base_model(self):
        dataset = _dataset()
        base_model = DemandLSTM(
            n_features=len(FEATURE_COLUMNS), hidden_size=8, num_layers=1, horizon=48
        )
        base_params_before = [p.clone() for p in base_model.parameters()]

        fine_tune(
            base_model,
            dataset,
            settings=Settings(model_batch_size=32),
            epochs=2,
            log_to_mlflow=False,
        )  # type: ignore[call-arg]

        for before, after in zip(
            base_params_before, base_model.parameters(), strict=True
        ):
            assert torch.equal(before, after)

    def test_returns_a_distinct_model_instance(self):
        dataset = _dataset()
        base_model = DemandLSTM(
            n_features=len(FEATURE_COLUMNS), hidden_size=8, num_layers=1, horizon=48
        )
        result = fine_tune(
            base_model,
            dataset,
            settings=Settings(model_batch_size=32),
            epochs=2,
            log_to_mlflow=False,
        )  # type: ignore[call-arg]
        assert result.model is not base_model

    def test_fine_tuned_weights_actually_change(self):
        dataset = _dataset()
        base_model = DemandLSTM(
            n_features=len(FEATURE_COLUMNS), hidden_size=8, num_layers=1, horizon=48
        )
        result = fine_tune(
            base_model,
            dataset,
            settings=Settings(model_train_lr=0.1, model_batch_size=32),  # type: ignore[call-arg]
            epochs=3,
            lr_scale=1.0,
            log_to_mlflow=False,
        )
        changed = any(
            not torch.equal(a, b)
            for a, b in zip(
                base_model.parameters(), result.model.parameters(), strict=True
            )
        )
        assert changed

    def test_final_val_loss_is_finite(self):
        dataset = _dataset()
        base_model = DemandLSTM(
            n_features=len(FEATURE_COLUMNS), hidden_size=8, num_layers=1, horizon=48
        )
        result = fine_tune(
            base_model,
            dataset,
            settings=Settings(model_batch_size=32),
            epochs=2,
            log_to_mlflow=False,
        )  # type: ignore[call-arg]
        assert np.isfinite(result.final_val_loss)
        assert result.run_id == ""  # log_to_mlflow=False -> no run created
