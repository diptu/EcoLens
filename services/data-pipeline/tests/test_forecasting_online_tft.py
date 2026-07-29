"""Tests for ecolens.forecasting.service.training.online_tft (root
TODO.md's "Fine tuning" section, "TFT monthly fine-tune"). Mirrors
test_forecasting_online.py's shape (LSTM's fine_tune) plus a
frozen-static-encoder check the LSTM has no equivalent of.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from ecolens.config import Settings
from ecolens.forecasting.model.tft import DemandTFT
from ecolens.forecasting.schema.features import FEATURE_COLUMNS
from ecolens.forecasting.service.training.online_tft import (
    _FROZEN_SUBMODULES,
    fine_tune_tft,
)
from ecolens.forecasting.service.training.train_tft import _region_to_idx
from ecolens.forecasting.service.windowing import build_windowed_dataset


def _dataset():
    rng = np.random.default_rng(11)
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


def _model(region_to_idx: dict[str, int]) -> DemandTFT:
    return DemandTFT(
        n_features=len(FEATURE_COLUMNS),
        d_model=8,
        num_heads=2,
        num_lstm_layers=1,
        num_regions=len(region_to_idx),
        static_dim=8,
        horizon=48,
        dropout=0.0,
    )


class TestFineTuneTFT:
    def test_does_not_mutate_the_base_model(self):
        dataset = _dataset()
        region_to_idx = _region_to_idx(dataset)
        base_model = _model(region_to_idx)
        base_params_before = [p.clone() for p in base_model.parameters()]

        fine_tune_tft(
            base_model,
            dataset,
            region_to_idx,
            settings=Settings(model_tft_batch_size=32),  # type: ignore[call-arg]
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
        result = fine_tune_tft(
            base_model,
            dataset,
            region_to_idx,
            settings=Settings(model_tft_batch_size=32),  # type: ignore[call-arg]
            epochs=2,
            log_to_mlflow=False,
        )
        assert result.model is not base_model

    def test_static_encoder_stays_frozen(self):
        """The whole point of TFT fine-tuning per root TODO.md: static
        embeddings (region, network_code) frozen, only VSN/attention/
        decoder adapt. Verifies the frozen submodules' weights are
        bit-for-bit identical after fine-tuning, while at least one
        non-frozen parameter actually changed (proving the freeze isn't
        accidentally freezing everything).
        """
        dataset = _dataset()
        region_to_idx = _region_to_idx(dataset)
        base_model = _model(region_to_idx)
        frozen_before = {
            name: [p.clone() for p in getattr(base_model, name).parameters()]
            for name in _FROZEN_SUBMODULES
        }

        result = fine_tune_tft(
            base_model,
            dataset,
            region_to_idx,
            settings=Settings(model_tft_train_lr=0.1, model_tft_batch_size=32),  # type: ignore[call-arg]
            epochs=3,
            lr=1.0,
            log_to_mlflow=False,
        )

        for name in _FROZEN_SUBMODULES:
            after = list(getattr(result.model, name).parameters())
            for before, after_p in zip(frozen_before[name], after, strict=True):
                assert torch.equal(before, after_p)

        non_frozen_changed = any(
            not torch.equal(a, b)
            for a, b in zip(
                base_model.parameters(), result.model.parameters(), strict=True
            )
        )
        assert non_frozen_changed

    def test_final_val_loss_is_finite(self):
        dataset = _dataset()
        region_to_idx = _region_to_idx(dataset)
        base_model = _model(region_to_idx)
        result = fine_tune_tft(
            base_model,
            dataset,
            region_to_idx,
            settings=Settings(model_tft_batch_size=32),  # type: ignore[call-arg]
            epochs=2,
            log_to_mlflow=False,
        )
        assert np.isfinite(result.final_val_loss)
        assert result.run_id == ""  # log_to_mlflow=False -> no run created
