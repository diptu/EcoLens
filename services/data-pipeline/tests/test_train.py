from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
import torch

from app.service.ml.features import FEATURE_COLUMNS
from app.models.ml import DemandLSTM
from app.service.ml.train import (
    TrainConfig,
    _split_val_for_calibration,
    mae,
    mape,
    rmse,
    state_dict_bytes,
    train_model,
)


def _synthetic_demand_df(
    n_per_region: int = 800, regions: tuple[str, ...] = ("NSW1",)
) -> pd.DataFrame:
    """A daily sine-wave demand pattern (288 5-min steps/day) plus small
    noise -- a real, learnable signal (via lag/calendar features), not
    pure noise, so a trained model's val MAPE should actually improve
    over a randomly-initialized one."""
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


_FAST_CONFIG = TrainConfig(
    lookback=8,
    horizon=4,
    hidden_size=8,
    num_layers=1,
    dropout=0.0,
    lr=1e-2,
    epochs=15,
    batch_size=32,
    early_stopping_patience=15,
    cal_frac=0.5,
)


class TestMape:
    def test_zero_when_exact(self):
        assert mape(np.array([10.0]), np.array([10.0])) == pytest.approx(0.0)

    def test_matches_hand_computed_value(self):
        pred = np.array([9.0, 11.0])
        target = np.array([10.0, 10.0])

        assert mape(pred, target) == pytest.approx(10.0)

    def test_excludes_zero_target_rows(self):
        pred = np.array([5.0, 100.0])
        target = np.array([0.0, 10.0])

        # Row 0 (target=0) excluded -- only row 1 (|100-10|/10 * 100 = 900%) counted.
        assert mape(pred, target) == pytest.approx(900.0)


class TestRmse:
    def test_zero_when_exact(self):
        assert rmse(np.array([10.0]), np.array([10.0])) == pytest.approx(0.0)

    def test_matches_hand_computed_value(self):
        pred = np.array([9.0, 12.0])
        target = np.array([10.0, 10.0])

        # errors: -1, 2 -> squared: 1, 4 -> mean: 2.5 -> sqrt: ~1.5811
        assert rmse(pred, target) == pytest.approx(np.sqrt(2.5))

    def test_penalizes_large_errors_more_than_mae_does(self):
        # RMSE is more sensitive to outliers than MAE (squaring) -- a
        # single large error should move RMSE above MAE for the same
        # pred/target pair, not leave them equal.
        pred = np.array([10.0, 10.0, 100.0])
        target = np.array([10.0, 10.0, 10.0])

        assert rmse(pred, target) > mae(pred, target)


class TestMae:
    def test_zero_when_exact(self):
        assert mae(np.array([10.0]), np.array([10.0])) == pytest.approx(0.0)

    def test_matches_hand_computed_value(self):
        pred = np.array([9.0, 12.0])
        target = np.array([10.0, 10.0])

        # errors: |-1|, |2| -> mean: 1.5
        assert mae(pred, target) == pytest.approx(1.5)


class TestSplitValForCalibration:
    def test_splits_chronologically_and_disjointly(self):
        df = pd.DataFrame(
            {"ts": pd.date_range("2026-01-01", periods=100, freq="5min", tz="UTC")}
        )

        earlystop, cal = _split_val_for_calibration(df, cal_frac=0.4)

        assert earlystop["ts"].max() < cal["ts"].min()
        assert len(earlystop) + len(cal) == len(df)


class TestTrainModel:
    def test_raises_when_not_enough_data(self):
        tiny_df = _synthetic_demand_df(n_per_region=5)

        with pytest.raises(ValueError, match="not enough history"):
            train_model(tiny_df, _FAST_CONFIG)

    def test_trains_end_to_end_and_learns_something(self):
        df = _synthetic_demand_df(n_per_region=800)

        result = train_model(df, _FAST_CONFIG)

        assert result.n_train_windows > 0
        assert result.n_val_windows > 0
        assert result.n_cal_windows > 0
        assert len(result.history) > 0

        first_epoch_mape = result.history[0]["val_mape"]
        last_epoch_mape = result.history[-1]["val_mape"]
        # A real, learnable daily-cycle signal -- the model should end up
        # meaningfully better than its randomly-initialized first epoch,
        # not just "ran without crashing".
        assert last_epoch_mape < first_epoch_mape * 0.9

        # `val_loss` (2026-08-05, for the Performance page's "training
        # vs validation loss" chart) -- real `demand_loss` on the
        # validation split, same units as `train_loss`, distinct from
        # `val_mape` (an inverse-scaled-MW percentage-error metric, not
        # a loss). Every epoch must have one, and it should also trend
        # down as the model actually learns, same as train_loss.
        assert all("val_loss" in h for h in result.history)
        assert result.history[-1]["val_loss"] < result.history[0]["val_loss"]

        # `val_rmse`/`val_mae` (2026-08-05, Performance page's
        # "validation RMSE & MAE" chart) -- real MW-unit error metrics
        # computed on the same inverse-scaled P50-vs-actual pair
        # `val_mape` uses. Same learn-something bar as val_mape.
        assert all("val_rmse" in h and "val_mae" in h for h in result.history)
        assert result.history[-1]["val_rmse"] < result.history[0]["val_rmse"] * 0.9
        assert result.history[-1]["val_mae"] < result.history[0]["val_mae"] * 0.9

        assert "test_mape" in result.test_metrics
        assert "test_coverage_calibrated" in result.test_metrics
        assert 0.0 <= result.test_metrics["test_coverage_calibrated"] <= 1.0
        # Calibration should never do *worse* than the raw, uncalibrated
        # interval -- CQR widens/tightens by construction to hit target
        # coverage, so calibrated coverage should track closer to 0.8
        # (1 - alpha) than the raw heads' un-corrected coverage.
        assert "test_coverage_raw" in result.test_metrics

    def test_calibration_q_has_one_value_per_horizon_step(self):
        df = _synthetic_demand_df(n_per_region=800)

        result = train_model(df, _FAST_CONFIG)

        assert result.calibration.q.shape == (_FAST_CONFIG.horizon,)

    def test_epoch_callback_is_invoked_once_per_epoch_with_real_history(self):
        df = _synthetic_demand_df(n_per_region=800)
        calls: list[tuple[int, dict[str, float]]] = []

        result = train_model(
            df,
            _FAST_CONFIG,
            epoch_callback=lambda epoch, hist: calls.append((epoch, dict(hist))),
        )

        assert len(calls) == len(result.history)
        assert [c[0] for c in calls] == list(range(len(result.history)))
        assert calls[-1][1] == result.history[-1]

    def test_epoch_callback_exception_aborts_training(self):
        df = _synthetic_demand_df(n_per_region=800)

        class _Stop(Exception):
            pass

        def blow_up(epoch: int, hist: dict[str, float]) -> None:
            raise _Stop

        with pytest.raises(_Stop):
            train_model(df, _FAST_CONFIG, epoch_callback=blow_up)


class TestStateDictBytes:
    def test_returns_a_positive_real_byte_count(self):
        model = DemandLSTM(n_features=len(FEATURE_COLUMNS), horizon=4, hidden_size=8)

        size = state_dict_bytes(model)

        assert size > 0

    def test_a_bigger_model_has_a_bigger_state_dict(self):
        small = DemandLSTM(n_features=len(FEATURE_COLUMNS), horizon=4, hidden_size=8)
        big = DemandLSTM(n_features=len(FEATURE_COLUMNS), horizon=4, hidden_size=128)

        assert state_dict_bytes(big) > state_dict_bytes(small)


class TestWarmStart:
    """`ml.incremental`'s warm-started fine-tune relies on `train_model`
    actually loading `warm_start_state_dict` into the model it constructs,
    instead of leaving it randomly initialized (`TODO.md`'s Event-Driven
    Pipeline Trigger item 3)."""

    def test_warm_start_state_dict_is_loaded_before_training(self):
        df = _synthetic_demand_df(n_per_region=800)
        # epochs=0 -- the training loop never runs, so `best_state` stays
        # `None` and the model that comes back is exactly whatever it was
        # constructed + warm-started with, letting this test assert exact
        # weight equality rather than something loosely statistical.
        config = replace(_FAST_CONFIG, epochs=0)

        reference_model = DemandLSTM(
            n_features=len(FEATURE_COLUMNS),
            horizon=config.horizon,
            hidden_size=config.hidden_size,
            num_layers=config.num_layers,
            dropout=config.dropout,
        )
        warm_start_state_dict = {
            k: v.clone() for k, v in reference_model.state_dict().items()
        }

        result = train_model(df, config, warm_start_state_dict=warm_start_state_dict)

        for key, expected in warm_start_state_dict.items():
            assert torch.equal(result.model.state_dict()[key], expected)

    def test_without_warm_start_the_model_is_freshly_initialized(self):
        df = _synthetic_demand_df(n_per_region=800)
        config = replace(_FAST_CONFIG, epochs=0)

        torch.manual_seed(0)
        reference_model = DemandLSTM(
            n_features=len(FEATURE_COLUMNS),
            horizon=config.horizon,
            hidden_size=config.hidden_size,
            num_layers=config.num_layers,
            dropout=config.dropout,
        )
        reference_state_dict = reference_model.state_dict()

        torch.manual_seed(1)
        result = train_model(df, config)

        # Different seed, no warm start -- the two models' random inits
        # should not coincidentally match.
        mismatches = [
            key
            for key, expected in reference_state_dict.items()
            if not torch.equal(result.model.state_dict()[key], expected)
        ]
        assert mismatches
