"""Integration tests for ecolens_forecast_api.forecasting.fuel_loader
against a real local MLflow tracking store -- same pattern
test_forecasting_loader.py uses for the LSTM loader. Logs a pyfunc model
the same shape data-pipeline's `train_fuel_ensemble.py` logs (a plain
`predict(context, model_input) -> DataFrame`), then confirms this
service's loader reads it back and can call `.predict()` on it with zero
knowledge of data-pipeline's own `FuelEnsemble`/LightGBM classes -- the
actual cross-service contract root TODO.md's "API & Registry Serving"
section depends on.
"""

from __future__ import annotations

import mlflow
import mlflow.pyfunc
import pandas as pd
import pytest
from mlflow.pyfunc import PythonModel

from ecolens_forecast_api.forecasting.features import FEATURE_COLUMNS
from ecolens_forecast_api.forecasting.fuel_loader import (
    FuelEnsembleLoadError,
    FuelEnsembleLoader,
)
from ecolens_forecast_api.forecasting.normalization import FUEL_COLUMNS
from ecolens_forecast_api.settings import ForecastApiSettings


class _FixedFuelPyfuncModel(PythonModel):
    def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
        return pd.DataFrame(
            {
                fuel: [float(i + 1)] * len(model_input)
                for i, fuel in enumerate(FUEL_COLUMNS)
            }
        )


@pytest.fixture
def settings(tmp_path, monkeypatch) -> ForecastApiSettings:
    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("fuel_loader_test")
    return ForecastApiSettings(
        mlflow_tracking_uri=uri,
        mlflow_registered_model_name_fuel_ensemble="fuel_loader_test_model",
        model_alias="production",
        mlflow_http_timeout_seconds=5,
        mlflow_http_max_retries=0,
    )


def _log_and_register(settings: ForecastApiSettings) -> str:
    with mlflow.start_run() as run:
        mlflow.pyfunc.log_model(
            name="model", python_model=_FixedFuelPyfuncModel(), pip_requirements=[]
        )
        run_id = run.info.run_id

    mv = mlflow.register_model(
        f"runs:/{run_id}/model", settings.mlflow_registered_model_name_fuel_ensemble
    )
    client = mlflow.tracking.MlflowClient()
    client.set_registered_model_alias(
        settings.mlflow_registered_model_name_fuel_ensemble,
        settings.model_alias,
        mv.version,
    )
    return str(mv.version)


class TestFuelEnsembleLoader:
    def test_load_current_returns_none_when_nothing_registered(self, settings):
        loader = FuelEnsembleLoader(settings)
        assert loader.load_current() is None

    def test_load_current_reconstructs_a_working_model(self, settings):
        version = _log_and_register(settings)
        loaded = FuelEnsembleLoader(settings).load_current()

        assert loaded is not None
        assert loaded.version == version

        row = pd.DataFrame([{col: 1.0 for col in FEATURE_COLUMNS}])
        preds = loaded.model.predict(row)
        assert set(preds.columns) == set(FUEL_COLUMNS)

    def test_reassigning_alias_changes_what_load_current_returns(self, settings):
        v1 = _log_and_register(settings)
        loader = FuelEnsembleLoader(settings)
        assert loader.load_current().version == v1

        v2 = _log_and_register(settings)
        assert v2 != v1
        assert loader.load_current().version == v2

    def test_corrupt_run_id_raises_fuel_ensemble_load_error(
        self, settings, monkeypatch
    ):
        loader = FuelEnsembleLoader(settings)

        class _FakeMV:
            run_id = "does-not-exist"
            version = "1"

        monkeypatch.setattr(
            loader.client, "get_model_version_by_alias", lambda *a, **k: _FakeMV()
        )
        with pytest.raises(FuelEnsembleLoadError):
            loader.load_current()
