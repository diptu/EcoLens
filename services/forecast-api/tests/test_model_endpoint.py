from __future__ import annotations

from datetime import UTC, datetime

from app.main import app
from app.api.v1.deps import get_model_registry
from app.api.v1.model import routes as model_routes
from app.service.ml.registry import ModelVersionSummary, PromotionRejected


class _FakeBundle:
    version = "3"
    stage = "Production"
    run_id = "run-abc"
    loaded_at = datetime(2026, 1, 1, tzinfo=UTC)
    git_sha = "deadbeef"
    horizon = 48
    lookback = 48
    metrics = {"test_mape": 4.2}


class _FakeRegistry:
    def __init__(self, bundle=None):
        self.bundle = bundle


def test_not_loaded_reports_status(client):
    app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(bundle=None)
    try:
        response = client.get("/v1/model")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_loaded"
    assert body["version"] is None


def test_loaded_reports_bundle_metadata(client):
    app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
        bundle=_FakeBundle()
    )
    try:
        response = client.get("/v1/model")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "loaded"
    assert body["version"] == "3"
    assert body["stage"] == "Production"
    assert body["run_id"] == "run-abc"
    assert body["metrics"] == {"test_mape": 4.2}


def test_versions_returns_every_registered_version(monkeypatch, client):
    # Ordering itself (newest first) is `list_versions`'s own job, tested
    # against a mocked MLflow client in test_ml_registry.py -- this test
    # only checks the route passes the data through/shapes it correctly.
    older = ModelVersionSummary(
        version="2",
        stage="Archived",
        run_id="run-2",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        metrics={"test_mape": 5.1},
        git_sha="cafebabe",
    )
    newer = ModelVersionSummary(
        version="3",
        stage="Production",
        run_id="run-3",
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
        metrics={"test_mape": 4.2},
        git_sha="deadbeef",
    )

    async def _fake_list_versions(model_name):
        return [newer, older]

    monkeypatch.setattr(model_routes, "list_versions", _fake_list_versions)

    response = client.get("/v1/model/versions")

    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["version"] == "3"
    assert body["data"][1]["version"] == "2"
    assert body["data"][0]["stage"] == "Production"
    assert body["data"][0]["metrics"] == {"test_mape": 4.2}
    assert body["data"][1]["git_sha"] == "cafebabe"


def test_versions_returns_empty_list_before_any_model_is_registered(
    monkeypatch, client
):
    async def _fake_list_versions(model_name):
        return []

    monkeypatch.setattr(model_routes, "list_versions", _fake_list_versions)

    response = client.get("/v1/model/versions")

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_promote_returns_the_updated_version(monkeypatch, client):
    updated = ModelVersionSummary(
        version="3",
        stage="Production",
        run_id="run-3",
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
        metrics={"test_mape": 4.2},
        git_sha="deadbeef",
    )

    async def _fake_promote_version(model_name, version, stage):
        assert version == "3"
        assert stage == "Production"
        return updated

    monkeypatch.setattr(model_routes, "promote_version", _fake_promote_version)

    response = client.post("/v1/model/versions/3/promote", json={"stage": "Production"})

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "Production"
    assert body["version"] == "3"


def test_promote_returns_409_when_the_gate_rejects_it(monkeypatch, client):
    async def _fake_promote_version(model_name, version, stage):
        raise PromotionRejected("version 3's test_mape is worse")

    monkeypatch.setattr(model_routes, "promote_version", _fake_promote_version)

    response = client.post("/v1/model/versions/3/promote", json={"stage": "Production"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "worse_than_production"


def test_promote_returns_404_for_an_unknown_version(monkeypatch, client):
    from mlflow.exceptions import MlflowException
    from mlflow.protos.databricks_pb2 import RESOURCE_DOES_NOT_EXIST

    async def _fake_promote_version(model_name, version, stage):
        raise MlflowException("not found", error_code=RESOURCE_DOES_NOT_EXIST)

    monkeypatch.setattr(model_routes, "promote_version", _fake_promote_version)

    response = client.post(
        "/v1/model/versions/999/promote", json={"stage": "Production"}
    )

    assert response.status_code == 404


def test_promote_returns_503_when_the_registry_is_unreachable(monkeypatch, client):
    # Confirmed live against this repo's real dev MLflow config: a bad
    # tracking URI/auth failure raises `MlflowException` with a
    # `PERMISSION_DENIED`/`INTERNAL_ERROR` code, *not*
    # `RESOURCE_DOES_NOT_EXIST` -- collapsing every `MlflowException`
    # into 404 would mislabel this as "version doesn't exist" instead of
    # "the registry itself is unreachable".
    from mlflow.exceptions import MlflowException

    async def _fake_promote_version(model_name, version, stage):
        raise MlflowException("API request failed with error code 403")

    monkeypatch.setattr(model_routes, "promote_version", _fake_promote_version)

    response = client.post("/v1/model/versions/3/promote", json={"stage": "Production"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "registry_unavailable"


def test_promote_rejects_an_invalid_stage(client):
    response = client.post("/v1/model/versions/3/promote", json={"stage": "Deleted"})

    assert response.status_code == 422


def test_versions_returns_503_when_the_registry_is_unreachable(monkeypatch, client):
    from mlflow.exceptions import MlflowException

    async def _fake_list_versions(model_name):
        raise MlflowException("API request failed with error code 403")

    monkeypatch.setattr(model_routes, "list_versions", _fake_list_versions)

    response = client.get("/v1/model/versions")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "registry_unavailable"
