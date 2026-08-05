from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
import torch

from app.models.tft import DemandTFT
from app.service.ml.train import TrainConfig
from app.service.ml.train_tft import (
    DECODER_COLUMNS,
    ENCODER_COLUMNS,
    TFTTrainConfig,
    train_tft_model,
)


def _synthetic_demand_df(
    n_per_region: int = 800, regions: tuple[str, ...] = ("NSW1",)
) -> pd.DataFrame:
    """Same synthetic daily sine-wave demand pattern `test_train.py`'s
    `_synthetic_demand_df` uses -- a real, learnable signal via
    lag/calendar features."""
    rng = np.random.default_rng(7)
    frames = []
    for region in regions:
        ts = pd.date_range("2026-01-01", periods=n_per_region, freq="5min", tz="UTC")
        t = np.arange(n_per_region)
        demand = (
            5000 + 1000 * np.sin(2 * np.pi * t / 288) + rng.normal(0, 20, n_per_region)
        )
        temp = 20 + 5 * np.sin(2 * np.pi * t / 288)
        frames.append(
            pd.DataFrame(
                {
                    "ts": ts,
                    "region": region,
                    "demand_mw": demand,
                    "price_mwh": 50 + rng.normal(0, 2, n_per_region),
                    "total_generation_mw": demand * 1.1,
                    "total_renewable_mw": demand * 0.3,
                    "temp_c": temp,
                    "apparent_temp_c": temp + 1,
                    "humidity_pct": np.full(n_per_region, 50.0),
                    "wind_speed_kmh": np.full(n_per_region, 10.0),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


_FAST_CONFIG = TFTTrainConfig(
    lookback=8,
    horizon=4,
    hidden_size=8,
    n_heads=2,
    dropout=0.0,
    lr=1e-2,
    epochs=15,
    batch_size=32,
    early_stopping_patience=15,
    cal_frac=0.5,
)


class TestTFTTrainConfig:
    def test_is_a_train_config_subclass(self):
        assert isinstance(_FAST_CONFIG, TrainConfig)

    def test_as_mlflow_params_includes_n_heads_and_base_fields(self):
        params = _FAST_CONFIG.as_mlflow_params()

        assert params["n_heads"] == 2
        assert params["lookback"] == 8
        assert params["horizon"] == 4

    def test_from_settings_returns_a_tft_train_config_with_n_heads_default(self):
        from app.core.config import get_settings

        config = TFTTrainConfig.from_settings(get_settings())

        assert isinstance(config, TFTTrainConfig)
        assert config.n_heads == 4


class TestEncoderDecoderColumns:
    def test_decoder_columns_are_a_subset_of_encoder_columns(self):
        assert set(DECODER_COLUMNS).issubset(set(ENCODER_COLUMNS))

    def test_encoder_columns_cover_every_feature_column(self):
        from app.service.ml.features import FEATURE_COLUMNS

        assert set(ENCODER_COLUMNS) == set(FEATURE_COLUMNS)


class TestTrainTftModel:
    def test_raises_when_not_enough_data(self):
        tiny_df = _synthetic_demand_df(n_per_region=5)

        with pytest.raises(ValueError, match="not enough history"):
            train_tft_model(tiny_df, _FAST_CONFIG)

    def test_trains_end_to_end_and_learns_something(self):
        df = _synthetic_demand_df(n_per_region=800)

        result = train_tft_model(df, _FAST_CONFIG)

        assert result.n_train_windows > 0
        assert result.n_val_windows > 0
        assert result.n_cal_windows > 0
        assert len(result.history) > 0
        assert isinstance(result.model, DemandTFT)

        first_epoch_mape = result.history[0]["val_mape"]
        last_epoch_mape = result.history[-1]["val_mape"]
        assert last_epoch_mape < first_epoch_mape * 0.95

        # `val_loss` (2026-08-05, `ml/train.py`'s `_compute_val_loss`
        # counterpart for TFT) -- see that module's test for the full
        # reasoning on why this, not `val_mape`, belongs on a
        # "training vs validation loss" chart.
        assert all("val_loss" in h for h in result.history)

        # `val_rmse`/`val_mae` (2026-08-05, `ml/train.py`'s `rmse`/`mae`
        # counterparts for TFT) -- real MW-unit error metrics for the
        # Performance page's "validation RMSE & MAE" chart.
        assert all("val_rmse" in h and "val_mae" in h for h in result.history)

        assert "test_mape" in result.test_metrics
        assert "test_coverage_calibrated" in result.test_metrics
        assert 0.0 <= result.test_metrics["test_coverage_calibrated"] <= 1.0

    def test_calibration_q_has_one_value_per_horizon_step(self):
        df = _synthetic_demand_df(n_per_region=800)

        result = train_tft_model(df, _FAST_CONFIG)

        assert result.calibration.q.shape == (_FAST_CONFIG.horizon,)

    def test_model_encoder_and_decoder_feature_counts_match_the_real_split(self):
        df = _synthetic_demand_df(n_per_region=800)

        result = train_tft_model(df, _FAST_CONFIG)

        assert result.model.encoder_vsn.n_vars == len(ENCODER_COLUMNS)
        assert result.model.decoder_vsn.n_vars == len(DECODER_COLUMNS)


class TestWarmStart:
    """`incremental_tft.py`'s warm-started fine-tune relies on
    `train_tft_model` actually loading `warm_start_state_dict` into the
    model it constructs, instead of leaving it randomly initialized --
    same real property `test_train.py`'s `TestWarmStart` verifies for
    `DemandLSTM`."""

    def test_warm_start_state_dict_is_loaded_before_training(self):
        df = _synthetic_demand_df(n_per_region=800)
        # epochs=0 -- the training loop never runs, so `best_state` stays
        # `None` and the model that comes back is exactly whatever it was
        # constructed + warm-started with.
        config = replace(_FAST_CONFIG, epochs=0)

        reference_model = DemandTFT(
            n_encoder_features=len(ENCODER_COLUMNS),
            n_decoder_features=len(DECODER_COLUMNS),
            horizon=config.horizon,
            hidden_size=config.hidden_size,
            n_heads=config.n_heads,
            dropout=config.dropout,
        )
        warm_start_state_dict = {
            k: v.clone() for k, v in reference_model.state_dict().items()
        }

        result = train_tft_model(
            df, config, warm_start_state_dict=warm_start_state_dict
        )

        for key, expected in warm_start_state_dict.items():
            assert torch.equal(result.model.state_dict()[key], expected)

    def test_without_warm_start_the_model_is_freshly_initialized(self):
        df = _synthetic_demand_df(n_per_region=800)
        config = replace(_FAST_CONFIG, epochs=0)

        torch.manual_seed(0)
        reference_model = DemandTFT(
            n_encoder_features=len(ENCODER_COLUMNS),
            n_decoder_features=len(DECODER_COLUMNS),
            horizon=config.horizon,
            hidden_size=config.hidden_size,
            n_heads=config.n_heads,
            dropout=config.dropout,
        )

        torch.manual_seed(0)
        result = train_tft_model(df, config)

        for key, expected in reference_model.state_dict().items():
            assert torch.equal(result.model.state_dict()[key], expected)
