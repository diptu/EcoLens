"""Tests for ecolens.forecasting.api (ECO-118's internal control surface).

`trigger_train`/`trigger_evaluate` fire real background jobs that need
a live warehouse Postgres + MLflow -- out of scope for a unit test, so
those two just verify the endpoint schedules the right job function
(monkeypatched) and returns immediately. `/status` runs for real
against a local SQLite MLflow store, same pattern as
test_forecasting_registry.py.
"""

from __future__ import annotations

import mlflow
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ecolens.config import get_settings
from ecolens.forecasting import api as api_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path}/mlflow.db")
    monkeypatch.setenv("MLFLOW_REGISTERED_MODEL_NAME", "api_test_model")
    get_settings.cache_clear()
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")

    app = FastAPI()
    app.include_router(api_module.router)
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


class TestTriggerTrain:
    def test_returns_started_and_runs_the_job(self, client, monkeypatch):
        called = {"ran": False}

        async def fake_job() -> None:
            called["ran"] = True

        monkeypatch.setattr(api_module, "_run_training_job", fake_job)
        response = client.post("/forecasting/train")

        assert response.status_code == 200
        assert response.json() == {"status": "started"}
        assert called["ran"] is True  # TestClient runs BackgroundTasks inline


class TestTriggerEvaluate:
    def test_returns_started_and_runs_the_job(self, client, monkeypatch):
        called = {"ran": False}

        async def fake_job() -> None:
            called["ran"] = True

        monkeypatch.setattr(api_module, "_run_evaluation_job", fake_job)
        response = client.post("/forecasting/evaluate")

        assert response.status_code == 200
        assert response.json() == {"status": "started"}
        assert called["ran"] is True


class TestModelStatus:
    def test_no_production_model_yet(self, client):
        response = client.get("/forecasting/status")
        assert response.status_code == 200
        body = response.json()
        assert body["has_production_model"] is False
        assert body["production_version"] is None

    def test_reports_registered_production_model(self, client):
        from ecolens.forecasting.features import FEATURE_COLUMNS
        from ecolens.forecasting.mlops.registry import ModelRegistry
        from ecolens.forecasting.models.lstm import DemandLSTM

        settings = get_settings()
        mlflow.set_experiment(settings.mlflow_experiment_name)
        model = DemandLSTM(
            n_features=len(FEATURE_COLUMNS), hidden_size=8, num_layers=1, horizon=48
        )
        with mlflow.start_run() as run:
            mlflow.log_metric("test_mape", 4.2)
            mlflow.pytorch.log_model(model, name="model", serialization_format="pickle")

        registry = ModelRegistry(settings=settings)
        registered = registry.register(run.info.run_id)
        registry.set_alias(settings.model_registry_alias, registered.version)

        response = client.get("/forecasting/status")
        body = response.json()
        assert body["has_production_model"] is True
        assert body["production_version"] == registered.version
        assert body["last_eval_metrics"]["test_mape"] == 4.2
