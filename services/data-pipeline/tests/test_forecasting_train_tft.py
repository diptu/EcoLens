"""Tests for ecolens.forecasting.service.training.train_tft. Mirrors
test_forecasting_train.py's mechanics coverage (loss decreasing, early
stopping, best-checkpoint selection) -- TFT has no checkpoint-continuation
mechanism (no incremental.py counterpart, out of scope per this session's
plan), so there's no `TestCheckpointContinuation`-equivalent here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from ecolens.config import Settings
from ecolens.forecasting.schema.features import FEATURE_COLUMNS
from ecolens.forecasting.service.evaluation.evaluate_tft import predict_split_tft
from ecolens.forecasting.service.training.losses import DemandForecastLoss
from ecolens.forecasting.service.training.train_tft import (
    _region_to_idx,
    train_tft_model,
)
from ecolens.forecasting.service.windowing import build_windowed_dataset


def _learnable_snapshot(
    *, n: int = 400, seed: int = 0, regions=("NSW1", "QLD1")
) -> pd.DataFrame:
    """A demand series with a genuine learnable diurnal pattern, per
    region, plus a per-region offset -- so the static covariate actually
    carries useful signal, not just noise.
    """
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


def _tft_settings(**overrides) -> Settings:
    kwargs = dict(
        model_tft_train_epochs=10,
        model_tft_d_model=16,
        model_tft_num_heads=2,
        model_tft_static_dim=8,
        model_tft_batch_size=32,
        model_early_stop_patience=10,
    )
    kwargs.update(overrides)
    return Settings(**kwargs)  # type: ignore[call-arg]


class TestRegionToIdx:
    def test_covers_every_region_deterministically(self):
        ds = build_windowed_dataset(_learnable_snapshot(), lookback=48, horizon=48)
        mapping = _region_to_idx(ds)
        assert set(mapping) == {"NSW1", "QLD1"}
        assert mapping == {"NSW1": 0, "QLD1": 1}  # sorted, deterministic


class TestTrainTFTModel:
    def test_loss_decreases_over_training(self):
        ds = build_windowed_dataset(_learnable_snapshot(), lookback=48, horizon=48)
        result = train_tft_model(ds, settings=_tft_settings(), log_to_mlflow=False)
        assert result.epochs_trained == 10
        assert result.best_val_loss < 0.9

    def test_early_stopping_triggers(self):
        ds = build_windowed_dataset(
            _learnable_snapshot(seed=1), lookback=48, horizon=48
        )
        settings = _tft_settings(
            model_tft_train_epochs=100,
            model_tft_train_lr=0.05,
            model_early_stop_patience=2,
        )
        result = train_tft_model(ds, settings=settings, log_to_mlflow=False)
        assert result.epochs_trained < 100

    def test_returned_model_is_the_best_checkpoint_not_the_last(self):
        ds = build_windowed_dataset(
            _learnable_snapshot(seed=2), lookback=48, horizon=48
        )
        settings = _tft_settings(
            model_tft_train_epochs=30,
            model_tft_train_lr=0.05,
            model_early_stop_patience=3,
        )
        result = train_tft_model(ds, settings=settings, log_to_mlflow=False)

        loss_fn = DemandForecastLoss()
        region_idx = torch.tensor(
            [result.region_to_idx[r] for r in ds.val.region], dtype=torch.long
        )
        with torch.no_grad():
            outputs, _ = result.model(ds.val.x, region_idx)
            actual_loss, _ = loss_fn(outputs, ds.val.y)
        assert actual_loss.item() == pytest.approx(result.best_val_loss, rel=1e-3)

    def test_region_to_idx_feeds_evaluation_without_key_errors(self):
        # Regression guard: predict_split_tft must be able to map every
        # region in every split through the mapping train_tft_model
        # returns -- would KeyError if a split ever saw a region absent
        # from the training-derived mapping.
        ds = build_windowed_dataset(_learnable_snapshot(), lookback=48, horizon=48)
        result = train_tft_model(
            ds, settings=_tft_settings(model_tft_train_epochs=1), log_to_mlflow=False
        )
        preds = predict_split_tft(
            result.model, ds.test, ds.scaler, result.region_to_idx
        )
        assert preds["p50"].shape == ds.test.y.shape
