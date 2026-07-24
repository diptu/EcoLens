"""Tests for ecolens.forecasting.api (ECO-118's internal control surface).

`trigger_train`/`trigger_evaluate` fire real background jobs that need
a live warehouse Postgres + MLflow -- out of scope for a unit test, so
those two just verify the endpoint schedules the right job function
(monkeypatched) and returns immediately. `/status` runs for real
against a local SQLite MLflow store, same pattern as
test_forecasting_registry.py.
"""

from __future__ import annotations

from datetime import date

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
    api_module._jobs.clear()

    app = FastAPI()
    app.include_router(api_module.router)
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
    api_module._jobs.clear()


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


class TestTriggerTrainIncrementalChunk:
    def test_returns_started_and_runs_the_job(self, client, monkeypatch):
        calls = []

        async def fake_job(chunk_start, chunk_end, prior_run_id, evaluate_and_promote):
            calls.append((chunk_start, chunk_end, prior_run_id, evaluate_and_promote))
            return {"run_id": "abc123", "best_val_loss": 0.1}

        monkeypatch.setattr(api_module, "_run_incremental_chunk_job", fake_job)
        response = client.post(
            "/forecasting/train-incremental-chunk",
            params={"start_date": "2023-01-01", "end_date": "2023-12-31"},
        )

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body.pop("job_id"), str)
        assert body == {
            "status": "started",
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
        }
        assert calls == [(date(2023, 1, 1), date(2023, 12, 31), None, False)]

    def test_passes_through_prior_run_id_and_evaluate_flag(self, client, monkeypatch):
        calls = []

        async def fake_job(chunk_start, chunk_end, prior_run_id, evaluate_and_promote):
            calls.append((chunk_start, chunk_end, prior_run_id, evaluate_and_promote))
            return {"run_id": "def456"}

        monkeypatch.setattr(api_module, "_run_incremental_chunk_job", fake_job)
        client.post(
            "/forecasting/train-incremental-chunk",
            params={
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "prior_run_id": "abc123",
                "evaluate_and_promote": "true",
            },
        )

        assert calls == [(date(2024, 1, 1), date(2024, 12, 31), "abc123", True)]

    def test_end_before_start_422s(self, client):
        response = client.post(
            "/forecasting/train-incremental-chunk",
            params={"start_date": "2023-12-31", "end_date": "2023-01-01"},
        )
        assert response.status_code == 422

    def test_poll_reports_completed_result(self, client, monkeypatch):
        async def fake_job(chunk_start, chunk_end, prior_run_id, evaluate_and_promote):
            return {"run_id": "abc123", "best_val_loss": 0.1}

        monkeypatch.setattr(api_module, "_run_incremental_chunk_job", fake_job)
        trigger = client.post(
            "/forecasting/train-incremental-chunk",
            params={"start_date": "2023-01-01", "end_date": "2023-12-31"},
        )
        job_id = trigger.json()["job_id"]

        status = client.get(f"/forecasting/train-incremental-chunk/{job_id}")
        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "completed"
        assert body["result"] == {"run_id": "abc123", "best_val_loss": 0.1}
        assert body["error"] is None

    def test_poll_reports_failure(self, client, monkeypatch):
        async def fake_job(chunk_start, chunk_end, prior_run_id, evaluate_and_promote):
            raise RuntimeError("no warehouse data for this range")

        monkeypatch.setattr(api_module, "_run_incremental_chunk_job", fake_job)
        trigger = client.post(
            "/forecasting/train-incremental-chunk",
            params={"start_date": "2023-01-01", "end_date": "2023-12-31"},
        )
        job_id = trigger.json()["job_id"]

        status = client.get(f"/forecasting/train-incremental-chunk/{job_id}")
        body = status.json()
        assert body["status"] == "failed"
        assert body["error"] == "no warehouse data for this range"

    def test_poll_unknown_job_id_404s(self, client):
        response = client.get("/forecasting/train-incremental-chunk/no-such-job")
        assert response.status_code == 404


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
