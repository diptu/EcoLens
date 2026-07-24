"""Integration tests for ecolens_forecast_api.forecasting.loader (ECO-F03,
root TODO's ECO-T01 "integration test coverage for the ML registry")
against a *real* local MLflow tracking store (SQLite + local artifact
dir under `tmp_path`) -- same pattern data-pipeline's own
test_forecasting_registry.py uses. This is the actual cross-service
contract: data-pipeline writes these exact artifacts
(mlops/registry.py's log_model_artifacts + train.py's scaler.json),
this service reads them back with zero knowledge of data-pipeline's
own DemandLSTM class.
"""

from __future__ import annotations

import mlflow
import numpy as np
import pytest
import torch

from ecolens_forecast_api.forecasting.loader import ModelLoadError, ModelLoader
from ecolens_forecast_api.forecasting.model import DemandLSTM
from ecolens_forecast_api.settings import ForecastApiSettings

ARCHITECTURE = {
    "n_features": 24,
    "hidden_size": 8,
    "num_layers": 1,
    "horizon": 48,
    "dropout": 0.0,
}


@pytest.fixture
def settings(tmp_path, monkeypatch) -> ForecastApiSettings:
    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("loader_test")
    return ForecastApiSettings(
        mlflow_tracking_uri=uri,
        mlflow_registered_model_name="loader_test_model",
        model_alias="production",
        mlflow_http_timeout_seconds=5,
        mlflow_http_max_retries=0,
    )


def _log_and_register(
    settings: ForecastApiSettings, *, with_calibration: bool = True
) -> str:
    """Writes exactly the artifacts data-pipeline's training pipeline
    does (`mlops/registry.py`'s `log_model_artifacts` + `train.py`'s
    `scaler.json` + `evaluate.py`'s `conformal_calibration.json`), then
    registers + aliases a version -- the same real cross-service
    contract this loader has to read, not a simplified stand-in for it.
    Registration itself has to point at the *pickled* model artifact
    (MLflow 3.x's registry requires a "logged model" entity there,
    which a plain `log_state_dict`/`log_dict` artifact isn't) even
    though this service's loader never reads that pickled copy -- only
    `data-pipeline`'s own `ModelRegistry.load_by_alias` does.
    """
    model = DemandLSTM(**ARCHITECTURE)
    with mlflow.start_run() as run:
        mlflow.pytorch.log_model(
            model, name="model", serialization_format="pickle", pip_requirements=[]
        )
        mlflow.pytorch.log_state_dict(
            model.state_dict(), artifact_path="model_state_dict"
        )
        mlflow.log_dict(ARCHITECTURE, "model_architecture.json")
        mlflow.log_dict(
            {"mean": [0.0] * 24, "std": [1.0] * 24, "columns": list(range(24))},
            "scaler.json",
        )
        if with_calibration:
            mlflow.log_dict(
                {"q_hat": [1.0] * 48, "alpha": 0.1}, "conformal_calibration.json"
            )
        run_id = run.info.run_id

    mv = mlflow.register_model(
        f"runs:/{run_id}/model", settings.mlflow_registered_model_name
    )
    client = mlflow.tracking.MlflowClient()
    client.set_registered_model_alias(
        settings.mlflow_registered_model_name, settings.model_alias, mv.version
    )
    return str(mv.version)


class TestModelLoader:
    def test_load_current_returns_none_when_nothing_registered(self, settings):
        loader = ModelLoader(settings)
        assert loader.load_current() is None

    def test_load_current_reconstructs_a_working_model(self, settings):
        version = _log_and_register(settings)
        loader = ModelLoader(settings)
        loaded = loader.load_current()

        assert loaded is not None
        assert loaded.version == version
        assert isinstance(loaded.model, DemandLSTM)

        x = torch.randn(1, 48, 24)
        with torch.no_grad():
            outputs, _ = loaded.model(x)
        assert outputs["p50"].shape == (1, 48)

    def test_loads_scaler(self, settings):
        _log_and_register(settings)
        loaded = ModelLoader(settings).load_current()
        assert loaded.scaler.mean.shape == (24,)
        assert np.allclose(loaded.scaler.std, 1.0)

    def test_loads_calibration_when_present(self, settings):
        _log_and_register(settings, with_calibration=True)
        loaded = ModelLoader(settings).load_current()
        assert loaded.calibration is not None
        assert loaded.calibration.alpha == 0.1

    def test_degrades_gracefully_when_calibration_missing(self, settings):
        _log_and_register(settings, with_calibration=False)
        loaded = ModelLoader(settings).load_current()
        assert loaded is not None
        assert loaded.calibration is None

    def test_reassigning_alias_changes_what_load_current_returns(self, settings):
        v1 = _log_and_register(settings)
        loader = ModelLoader(settings)
        assert loader.load_current().version == v1

        v2 = _log_and_register(settings)
        assert v2 != v1
        assert loader.load_current().version == v2

    def test_corrupt_run_id_raises_model_load_error(self, settings):
        loader = ModelLoader(settings)
        with pytest.raises(ModelLoadError):
            loader._load_version(run_id="does-not-exist", version="1")
