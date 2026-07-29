"""Tests for ecolens.forecasting.service.training.train_timesfm. Every
test here injects a fake `TimesFMBackbone` (see `_FakeBackbone` below)
instead of the real `FrozenTimesFM` -- the real one downloads a ~2GB
checkpoint on first use, which has no place in the default test suite
(mirrors this repo's existing pattern of never requiring a live external
dependency for `pytest` by default). The real backbone only ever runs in
the live verification step documented in root TODO.md's "Stand up
TimesFM" entry.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from ecolens.config import Settings
from ecolens.forecasting.schema.features import FEATURE_COLUMNS
from ecolens.forecasting.service.training.losses import DemandForecastLoss
from ecolens.forecasting.service.training.train_timesfm import (
    _region_to_idx,
    train_timesfm_model,
)
from ecolens.forecasting.service.windowing import build_windowed_dataset


class _FakeBackbone:
    """Stands in for `FrozenTimesFM` -- deterministic, instant, and
    (importantly) actually *learnable*: the true demand series has a
    diurnal sine pattern (see `_learnable_snapshot`) plus a per-region
    offset, and this fake forecasts "last observed value, repeated" --
    systematically biased in a way a trained head should be able to
    correct, same spirit as `test_forecasting_train.py`'s own
    `_learnable_snapshot` proving LSTM training actually learns something.
    """

    def forecast_raw(self, contexts, *, horizon):
        last = contexts[:, -1:]
        p50 = np.repeat(last, horizon, axis=1)
        return p50 - 200.0, p50, p50 + 200.0


def _learnable_snapshot(
    *, n: int = 400, seed: int = 0, regions=("NSW1", "QLD1")
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


def _timesfm_settings(**overrides) -> Settings:
    kwargs = dict(
        model_timesfm_train_epochs=10,
        model_timesfm_hidden_dim=16,
        model_timesfm_static_dim=8,
        model_timesfm_batch_size=32,
        model_early_stop_patience=10,
    )
    kwargs.update(overrides)
    return Settings(**kwargs)  # type: ignore[call-arg]


class TestRegionToIdx:
    def test_covers_every_region_deterministically(self):
        ds = build_windowed_dataset(_learnable_snapshot(), lookback=48, horizon=48)
        mapping = _region_to_idx(ds)
        assert mapping == {"NSW1": 0, "QLD1": 1}


class TestTrainTimesFMModel:
    def test_loss_decreases_over_training(self):
        ds = build_windowed_dataset(_learnable_snapshot(), lookback=48, horizon=48)
        result = train_timesfm_model(
            ds,
            settings=_timesfm_settings(),
            backbone=_FakeBackbone(),
            log_to_mlflow=False,
        )
        assert result.epochs_trained == 10
        assert result.best_val_loss < 0.9

    def test_early_stopping_triggers(self):
        ds = build_windowed_dataset(
            _learnable_snapshot(seed=1), lookback=48, horizon=48
        )
        settings = _timesfm_settings(
            model_timesfm_train_epochs=100,
            model_timesfm_train_lr=0.05,
            model_early_stop_patience=2,
        )
        result = train_timesfm_model(
            ds, settings=settings, backbone=_FakeBackbone(), log_to_mlflow=False
        )
        assert result.epochs_trained < 100

    def test_returned_model_is_the_best_checkpoint_not_the_last(self):
        ds = build_windowed_dataset(
            _learnable_snapshot(seed=2), lookback=48, horizon=48
        )
        settings = _timesfm_settings(
            model_timesfm_train_epochs=30,
            model_timesfm_train_lr=0.05,
            model_early_stop_patience=3,
        )
        result = train_timesfm_model(
            ds, settings=settings, backbone=_FakeBackbone(), log_to_mlflow=False
        )

        loss_fn = DemandForecastLoss()
        val_raw = result.raw_forecasts["val"]
        region_idx = torch.tensor(
            [result.region_to_idx[r] for r in ds.val.region], dtype=torch.long
        )
        with torch.no_grad():
            outputs = result.model(val_raw.p10, val_raw.p50, val_raw.p90, region_idx)
            actual_loss, _ = loss_fn(outputs, ds.val.y)
        assert actual_loss.item() == pytest.approx(result.best_val_loss, rel=1e-3)

    def test_raw_forecasts_cover_every_split(self):
        ds = build_windowed_dataset(_learnable_snapshot(), lookback=48, horizon=48)
        result = train_timesfm_model(
            ds,
            settings=_timesfm_settings(model_timesfm_train_epochs=1),
            backbone=_FakeBackbone(),
            log_to_mlflow=False,
        )
        assert set(result.raw_forecasts) == {"train", "val", "calibration", "test"}
        assert result.raw_forecasts["test"].p50.shape == ds.test.y.shape
