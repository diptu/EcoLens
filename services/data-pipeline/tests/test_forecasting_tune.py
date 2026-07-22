"""Tests for ecolens.forecasting.training.tune (ECO-113), against a
real local MLflow tracking store (same pattern as
test_forecasting_registry.py) since nested-run logging is the whole
point of this module and mocking MLflow out would just test the mock.
"""

from __future__ import annotations

import mlflow
import numpy as np
import pandas as pd
import pytest

from ecolens.config import Settings
from ecolens.forecasting.features import FEATURE_COLUMNS, build_windowed_dataset
from ecolens.forecasting.training.tune import tune


@pytest.fixture
def mlflow_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("tune_test")
    return uri


def _dataset():
    rng = np.random.default_rng(8)
    n = 300
    ts = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    df = pd.DataFrame({"ts_30": ts, "region": "NSW1"})
    t = np.arange(n)
    df["demand_mw"] = 5000 + 300 * np.sin(2 * np.pi * t / 48) + rng.normal(0, 20, n)
    for col in FEATURE_COLUMNS:
        if col == "demand_mw":
            continue
        df[col] = (
            rng.integers(0, 2, size=n)
            if col in ("is_holiday", "is_weekend")
            else rng.normal(size=n)
        )
    return build_windowed_dataset(df, lookback=48, horizon=48)


class TestTune:
    def test_runs_the_requested_number_of_trials(self, mlflow_tmp):
        dataset = _dataset()
        settings = Settings(
            model_train_epochs=2, model_batch_size=32, mlflow_tracking_uri=mlflow_tmp
        )  # type: ignore[call-arg]
        result = tune(dataset, settings=settings, n_trials=3)
        assert len(result.study.trials) == 3

    def test_best_params_cover_the_search_space_fields(self, mlflow_tmp):
        dataset = _dataset()
        settings = Settings(
            model_train_epochs=2, model_batch_size=32, mlflow_tracking_uri=mlflow_tmp
        )  # type: ignore[call-arg]
        result = tune(dataset, settings=settings, n_trials=2)
        assert set(result.best_params) == {"hidden_size", "num_layers", "dropout", "lr"}

    def test_best_run_id_is_registerable(self, mlflow_tmp):
        from ecolens.forecasting.mlops.registry import ModelRegistry

        dataset = _dataset()
        settings = Settings(  # type: ignore[call-arg]
            model_train_epochs=2,
            model_batch_size=32,
            mlflow_tracking_uri=mlflow_tmp,
            mlflow_registered_model_name="tune_test_model",
        )
        result = tune(dataset, settings=settings, n_trials=2)

        registry = ModelRegistry(settings=settings)
        registered = registry.register(result.best_run_id)
        assert registered.version

    def test_defaults_n_trials_to_settings(self, mlflow_tmp):
        dataset = _dataset()
        settings = Settings(
            model_train_epochs=1,
            model_batch_size=32,
            mlflow_tracking_uri=mlflow_tmp,
            optuna_n_trials=2,
        )  # type: ignore[call-arg]
        result = tune(dataset, settings=settings)
        assert len(result.study.trials) == 2
