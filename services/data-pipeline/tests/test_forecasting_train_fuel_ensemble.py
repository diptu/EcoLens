"""Tests for ecolens.forecasting.service.training.train_fuel_ensemble.
Runs against a real local MLflow SQLite store (mlflow.pyfunc.log_model +
mlflow.pyfunc.load_model round-trip) -- the whole point of this module's
design (see its docstring) is that persistence never needs this package's
own FuelEnsemble class to load it back, so the round-trip itself is the
important thing to verify, not just that fit_fuel_ensemble ran.
"""

from __future__ import annotations

import mlflow
import mlflow.pyfunc
import numpy as np
import pandas as pd
import pytest

from ecolens.config import Settings, get_settings
from ecolens.forecasting.model.fuel_ensemble import FUEL_COLUMNS
from ecolens.forecasting.schema.features import FEATURE_COLUMNS
from ecolens.forecasting.service.training.train_fuel_ensemble import (
    train_fuel_ensemble_model,
)


def _joined_frame(n_per_region: int = 150, regions=("NSW1", "QLD1")) -> pd.DataFrame:
    rng = np.random.default_rng(5)
    frames = []
    for region in regions:
        ts = pd.date_range("2026-01-01", periods=n_per_region, freq="30min", tz="UTC")
        df = pd.DataFrame({"ts_30": ts, "region": region})
        for col in FEATURE_COLUMNS:
            df[col] = (
                rng.integers(0, 2, size=n_per_region)
                if col == "is_holiday"
                else rng.normal(size=n_per_region)
            )
        for fuel in FUEL_COLUMNS:
            df[fuel] = rng.normal(loc=50, scale=10, size=n_per_region)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


@pytest.fixture
def mlflow_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path}/mlflow.db")
    monkeypatch.setenv(
        "MLFLOW_EXPERIMENT_NAME_FUEL_ENSEMBLE", "test_fuel_ensemble_experiment"
    )
    get_settings.cache_clear()
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
    yield
    get_settings.cache_clear()


class TestTrainFuelEnsembleModel:
    def test_returns_mae_for_every_fuel(self):
        df = _joined_frame()
        result = train_fuel_ensemble_model(
            df,
            settings=Settings(model_fuel_n_estimators=20, model_fuel_num_leaves=7),  # type: ignore[call-arg]
            log_to_mlflow=False,
        )
        assert set(result.test_mae) == set(FUEL_COLUMNS)
        assert all(np.isfinite(v) for v in result.test_mae.values())
        assert result.test_mae_mean == pytest.approx(
            np.mean(list(result.test_mae.values()))
        )

    def test_raises_on_empty_input(self):
        empty = _joined_frame(n_per_region=0)
        with pytest.raises(ValueError, match="nothing to train"):
            train_fuel_ensemble_model(empty, log_to_mlflow=False)

    def test_logs_a_loadable_pyfunc_model_round_trip(self, mlflow_env):
        df = _joined_frame()
        result = train_fuel_ensemble_model(
            df,
            settings=Settings(model_fuel_n_estimators=20, model_fuel_num_leaves=7),  # type: ignore[call-arg]
        )
        assert result.run_id != ""

        loaded = mlflow.pyfunc.load_model(f"runs:/{result.run_id}/model")
        row = df.iloc[[0]][list(FEATURE_COLUMNS)]
        preds = loaded.predict(row)
        assert set(preds.columns) == set(FUEL_COLUMNS)
        assert len(preds) == 1

    def test_logs_test_mae_mean_metric(self, mlflow_env):
        df = _joined_frame()
        result = train_fuel_ensemble_model(
            df,
            settings=Settings(model_fuel_n_estimators=20, model_fuel_num_leaves=7),  # type: ignore[call-arg]
        )
        run = mlflow.get_run(result.run_id)
        assert run.data.metrics["test_mae_mean"] == pytest.approx(
            result.test_mae_mean, rel=1e-6
        )
