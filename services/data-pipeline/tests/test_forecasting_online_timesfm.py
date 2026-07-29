"""Tests for ecolens.forecasting.service.training.online_timesfm (root
TODO.md's "Fine tuning" section, "TimesFM monthly fine-tune"). Mirrors
test_forecasting_online.py's shape, with a fake backbone the same as
test_forecasting_train_timesfm.py uses -- the real FrozenTimesFM downloads
a ~2GB checkpoint on first use, no place in the default test suite.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from ecolens.config import Settings
from ecolens.forecasting.model.timesfm_head import TimesFMCalibrationHead
from ecolens.forecasting.schema.features import FEATURE_COLUMNS
from ecolens.forecasting.service.training.online_timesfm import fine_tune_timesfm
from ecolens.forecasting.service.training.train_tft import _region_to_idx
from ecolens.forecasting.service.windowing import build_windowed_dataset


class _FakeBackbone:
    def forecast_raw(self, contexts, *, horizon):
        last = contexts[:, -1:]
        p50 = np.repeat(last, horizon, axis=1)
        return p50 - 200.0, p50, p50 + 200.0


def _dataset():
    rng = np.random.default_rng(13)
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


def _model(region_to_idx: dict[str, int]) -> TimesFMCalibrationHead:
    return TimesFMCalibrationHead(
        horizon=48,
        num_regions=len(region_to_idx),
        static_dim=8,
        hidden_dim=8,
        dropout=0.0,
    )


class TestFineTuneTimesFM:
    def test_does_not_mutate_the_base_model(self):
        dataset = _dataset()
        region_to_idx = _region_to_idx(dataset)
        base_model = _model(region_to_idx)
        base_params_before = [p.clone() for p in base_model.parameters()]

        fine_tune_timesfm(
            base_model,
            dataset,
            region_to_idx,
            settings=Settings(model_timesfm_batch_size=32),  # type: ignore[call-arg]
            backbone=_FakeBackbone(),
            epochs=2,
            log_to_mlflow=False,
        )

        for before, after in zip(
            base_params_before, base_model.parameters(), strict=True
        ):
            assert torch.equal(before, after)

    def test_returns_a_distinct_model_instance(self):
        dataset = _dataset()
        region_to_idx = _region_to_idx(dataset)
        base_model = _model(region_to_idx)
        result = fine_tune_timesfm(
            base_model,
            dataset,
            region_to_idx,
            settings=Settings(model_timesfm_batch_size=32),  # type: ignore[call-arg]
            backbone=_FakeBackbone(),
            epochs=2,
            log_to_mlflow=False,
        )
        assert result.model is not base_model

    def test_fine_tuned_weights_actually_change(self):
        dataset = _dataset()
        region_to_idx = _region_to_idx(dataset)
        base_model = _model(region_to_idx)
        result = fine_tune_timesfm(
            base_model,
            dataset,
            region_to_idx,
            settings=Settings(model_timesfm_batch_size=32),  # type: ignore[call-arg]
            backbone=_FakeBackbone(),
            epochs=3,
            lr=0.1,
            log_to_mlflow=False,
        )
        changed = any(
            not torch.equal(a, b)
            for a, b in zip(
                base_model.parameters(), result.model.parameters(), strict=True
            )
        )
        assert changed

    def test_raw_forecasts_cover_every_split(self):
        dataset = _dataset()
        region_to_idx = _region_to_idx(dataset)
        base_model = _model(region_to_idx)
        result = fine_tune_timesfm(
            base_model,
            dataset,
            region_to_idx,
            settings=Settings(model_timesfm_batch_size=32),  # type: ignore[call-arg]
            backbone=_FakeBackbone(),
            epochs=1,
            log_to_mlflow=False,
        )
        assert set(result.raw_forecasts) == {"train", "val", "calibration", "test"}
        assert result.raw_forecasts["test"].p50.shape == dataset.test.y.shape

    def test_final_val_loss_is_finite(self):
        dataset = _dataset()
        region_to_idx = _region_to_idx(dataset)
        base_model = _model(region_to_idx)
        result = fine_tune_timesfm(
            base_model,
            dataset,
            region_to_idx,
            settings=Settings(model_timesfm_batch_size=32),  # type: ignore[call-arg]
            backbone=_FakeBackbone(),
            epochs=2,
            log_to_mlflow=False,
        )
        assert np.isfinite(result.final_val_loss)
        assert result.run_id == ""  # log_to_mlflow=False -> no run created
