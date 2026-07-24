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


class TestCheckpointContinuation:
    """`initial_model_state`/`initial_optimizer_state` -- the mechanism
    `training/incremental.py`'s year-by-year chunked training relies on
    to avoid retraining from scratch (or resetting Adam's momentum) on
    every chunk.
    """

    def test_optimizer_state_is_populated_after_training(self):
        ds = build_windowed_dataset(_learnable_snapshot(), lookback=48, horizon=48)
        settings = Settings(  # type: ignore[call-arg]
            model_train_epochs=2, model_hidden_size=8, model_batch_size=32
        )
        result = train_model(ds, settings=settings, log_to_mlflow=False)

        assert result.optimizer_state is not None
        assert "state" in result.optimizer_state
        assert "param_groups" in result.optimizer_state
        # Adam tracks exp_avg/exp_avg_sq per parameter -- confirms this is
        # a real, populated optimizer checkpoint, not an empty shell.
        assert len(result.optimizer_state["state"]) > 0

    def test_zero_epochs_returns_exactly_the_initial_model_state(self):
        # With model_train_epochs=0 the training loop never runs, so the
        # returned model's weights are determined *only* by whether
        # initial_model_state got loaded at construction time -- the
        # cleanest possible proof that it actually did.
        ds = build_windowed_dataset(_learnable_snapshot(), lookback=48, horizon=48)
        settings = Settings(  # type: ignore[call-arg]
            model_train_epochs=3, model_hidden_size=8, model_batch_size=32
        )
        first = train_model(ds, settings=settings, log_to_mlflow=False)

        zero_epoch_settings = Settings(  # type: ignore[call-arg]
            model_train_epochs=0, model_hidden_size=8, model_batch_size=32
        )
        continued = train_model(
            ds,
            settings=zero_epoch_settings,
            log_to_mlflow=False,
            initial_model_state=first.model.state_dict(),
        )

        for key, value in first.model.state_dict().items():
            assert torch.equal(value, continued.model.state_dict()[key])

    def test_prior_optimizer_state_changes_the_training_trajectory(self):
        # Same starting weights, same one epoch of data (seeded shuffle),
        # but one continuation restores Adam's momentum and the other
        # starts it fresh at zero -- Adam's update rule depends on those
        # running estimates, so the two must diverge if the restored
        # state is actually being used rather than silently ignored.
        ds = build_windowed_dataset(_learnable_snapshot(), lookback=48, horizon=48)
        base_settings = Settings(  # type: ignore[call-arg]
            model_train_epochs=5,
            model_hidden_size=8,
            model_batch_size=32,
            model_train_lr=0.01,
        )
        base = train_model(ds, settings=base_settings, log_to_mlflow=False)

        one_epoch_settings = Settings(  # type: ignore[call-arg]
            model_train_epochs=1,
            model_hidden_size=8,
            model_batch_size=32,
            model_train_lr=0.01,
        )

        torch.manual_seed(0)
        with_prior_optimizer = train_model(
            ds,
            settings=one_epoch_settings,
            log_to_mlflow=False,
            initial_model_state=base.model.state_dict(),
            initial_optimizer_state=base.optimizer_state,
        )

        torch.manual_seed(0)
        fresh_optimizer = train_model(
            ds,
            settings=one_epoch_settings,
            log_to_mlflow=False,
            initial_model_state=base.model.state_dict(),
        )

        differs = any(
            not torch.equal(v, fresh_optimizer.model.state_dict()[k])
            for k, v in with_prior_optimizer.model.state_dict().items()
        )
        assert differs

    def test_mismatched_initial_state_shape_raises(self):
        # A state_dict from a *different* architecture (different
        # hidden_size) can't load into this one -- PyTorch itself
        # enforces this; confirms train_model doesn't silently swallow it.
        ds = build_windowed_dataset(_learnable_snapshot(), lookback=48, horizon=48)
        small = Settings(model_train_epochs=1, model_hidden_size=8)  # type: ignore[call-arg]
        small_result = train_model(ds, settings=small, log_to_mlflow=False)

        big = Settings(model_train_epochs=1, model_hidden_size=16)  # type: ignore[call-arg]
        with pytest.raises(RuntimeError):
            train_model(
                ds,
                settings=big,
                log_to_mlflow=False,
                initial_model_state=small_result.model.state_dict(),
            )
