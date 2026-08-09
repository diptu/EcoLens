from __future__ import annotations

from datetime import UTC, datetime

from app.main import app
from app.api.v1.deps import get_model_registry
from app.api.v1.model import routes as model_routes
from app.service.ml.registry import (
    DeletionRejected,
    LossCurve,
    LossCurvePoint,
    ModelVersionSummary,
    PromotionRejected,
)


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


def test_versions_uses_the_given_model_name_over_the_settings_default(
    monkeypatch, client
):
    """`todo-model-training.md` Phase 8: `?model_name=` lets the
    dashboard list a *different* architecture's registry (e.g.
    `lstm_demand_tft`), not just `Settings.mlflow_registry_model_name`."""
    captured = {}

    async def _fake_list_versions(model_name):
        captured["model_name"] = model_name
        return []

    monkeypatch.setattr(model_routes, "list_versions", _fake_list_versions)

    response = client.get("/v1/model/versions?model_name=lstm_demand_tft")

    assert response.status_code == 200
    assert response.json()["name"] == "lstm_demand_tft"
    assert captured["model_name"] == "lstm_demand_tft"


def test_versions_defaults_model_name_when_not_given(monkeypatch, client):
    captured = {}

    async def _fake_list_versions(model_name):
        captured["model_name"] = model_name
        return []

    monkeypatch.setattr(model_routes, "list_versions", _fake_list_versions)

    response = client.get("/v1/model/versions")

    assert response.status_code == 200
    assert captured["model_name"] == "lstm_demand"


def test_loss_curve_returns_the_merged_per_epoch_history(monkeypatch, client):
    async def _fake_get_loss_curve(model_name, version):
        assert model_name == "lstm_demand"
        assert version == "3"
        return LossCurve(
            run_id="run-3",
            points=[
                LossCurvePoint(
                    epoch=0,
                    train_loss=120.5,
                    val_loss=130.0,
                    val_mape=12.1,
                    val_rmse=610.2,
                    val_mae=505.1,
                ),
                LossCurvePoint(
                    epoch=1,
                    train_loss=95.2,
                    val_loss=101.4,
                    val_mape=9.8,
                    val_rmse=480.7,
                    val_mae=390.4,
                ),
            ],
        )

    monkeypatch.setattr(model_routes, "get_loss_curve", _fake_get_loss_curve)

    response = client.get("/v1/model/versions/3/loss-curve")

    assert response.status_code == 200
    body = response.json()
    assert body["model_name"] == "lstm_demand"
    assert body["version"] == "3"
    assert body["run_id"] == "run-3"
    assert body["points"] == [
        {
            "epoch": 0,
            "train_loss": 120.5,
            "val_loss": 130.0,
            "val_mape": 12.1,
            "val_rmse": 610.2,
            "val_mae": 505.1,
        },
        {
            "epoch": 1,
            "train_loss": 95.2,
            "val_loss": 101.4,
            "val_mape": 9.8,
            "val_rmse": 480.7,
            "val_mae": 390.4,
        },
    ]


def test_loss_curve_uses_the_given_model_name_over_the_settings_default(
    monkeypatch, client
):
    captured = {}

    async def _fake_get_loss_curve(model_name, version):
        captured["model_name"] = model_name
        return LossCurve(run_id="run-1", points=[])

    monkeypatch.setattr(model_routes, "get_loss_curve", _fake_get_loss_curve)

    response = client.get("/v1/model/versions/1/loss-curve?model_name=lstm_demand_tft")

    assert response.status_code == 200
    assert response.json()["model_name"] == "lstm_demand_tft"
    assert captured["model_name"] == "lstm_demand_tft"


def test_loss_curve_returns_empty_points_for_a_version_with_no_logged_history(
    monkeypatch, client
):
    async def _fake_get_loss_curve(model_name, version):
        return LossCurve(run_id="run-1", points=[])

    monkeypatch.setattr(model_routes, "get_loss_curve", _fake_get_loss_curve)

    response = client.get("/v1/model/versions/1/loss-curve")

    assert response.status_code == 200
    assert response.json()["points"] == []


def test_loss_curve_returns_404_for_an_unknown_version(monkeypatch, client):
    from mlflow.exceptions import MlflowException
    from mlflow.protos.databricks_pb2 import RESOURCE_DOES_NOT_EXIST

    async def _fake_get_loss_curve(model_name, version):
        raise MlflowException("not found", error_code=RESOURCE_DOES_NOT_EXIST)

    monkeypatch.setattr(model_routes, "get_loss_curve", _fake_get_loss_curve)

    response = client.get("/v1/model/versions/999/loss-curve")

    assert response.status_code == 404


def test_loss_curve_returns_503_when_the_registry_is_unreachable(monkeypatch, client):
    from mlflow.exceptions import MlflowException

    async def _fake_get_loss_curve(model_name, version):
        raise MlflowException("API request failed with error code 403")

    monkeypatch.setattr(model_routes, "get_loss_curve", _fake_get_loss_curve)

    response = client.get("/v1/model/versions/3/loss-curve")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "registry_unavailable"


def test_promote_uses_the_given_model_name_in_the_request_body(monkeypatch, client):
    captured = {}

    async def _fake_promote_version(model_name, version, stage, force=False):
        captured["model_name"] = model_name
        return ModelVersionSummary(
            version="3",
            stage="Production",
            run_id="run-3",
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
            metrics={},
            git_sha=None,
        )

    monkeypatch.setattr(model_routes, "promote_version", _fake_promote_version)

    response = client.post(
        "/v1/model/versions/3/promote",
        json={"stage": "Production", "model_name": "lstm_demand_tft"},
    )

    assert response.status_code == 200
    assert captured["model_name"] == "lstm_demand_tft"


def test_promote_returns_the_updated_version(monkeypatch, client):
    updated = ModelVersionSummary(
        version="3",
        stage="Production",
        run_id="run-3",
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
        metrics={"test_mape": 4.2},
        git_sha="deadbeef",
    )

    async def _fake_promote_version(model_name, version, stage, force=False):
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
    async def _fake_promote_version(model_name, version, stage, force=False):
        raise PromotionRejected("version 3's test_mape is worse")

    monkeypatch.setattr(model_routes, "promote_version", _fake_promote_version)

    response = client.post("/v1/model/versions/3/promote", json={"stage": "Production"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "worse_than_production"


def test_promote_returns_404_for_an_unknown_version(monkeypatch, client):
    from mlflow.exceptions import MlflowException
    from mlflow.protos.databricks_pb2 import RESOURCE_DOES_NOT_EXIST

    async def _fake_promote_version(model_name, version, stage, force=False):
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

    async def _fake_promote_version(model_name, version, stage, force=False):
        raise MlflowException("API request failed with error code 403")

    monkeypatch.setattr(model_routes, "promote_version", _fake_promote_version)

    response = client.post("/v1/model/versions/3/promote", json={"stage": "Production"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "registry_unavailable"


def test_promote_rejects_an_invalid_stage(client):
    response = client.post("/v1/model/versions/3/promote", json={"stage": "Deleted"})

    assert response.status_code == 422


def test_delete_version_succeeds_with_204(monkeypatch, client):
    captured = {}

    async def _fake_delete_model_version(model_name, version):
        captured["model_name"] = model_name
        captured["version"] = version

    monkeypatch.setattr(
        model_routes, "delete_model_version", _fake_delete_model_version
    )

    response = client.delete("/v1/model/versions/2")

    assert response.status_code == 204
    assert response.content == b""
    assert captured == {"model_name": "lstm_demand", "version": "2"}


def test_delete_version_uses_the_given_model_name_over_the_settings_default(
    monkeypatch, client
):
    captured = {}

    async def _fake_delete_model_version(model_name, version):
        captured["model_name"] = model_name

    monkeypatch.setattr(
        model_routes, "delete_model_version", _fake_delete_model_version
    )

    response = client.delete("/v1/model/versions/2?model_name=lstm_demand_tft")

    assert response.status_code == 204
    assert captured["model_name"] == "lstm_demand_tft"


def test_delete_version_returns_409_when_it_is_the_production_version(
    monkeypatch, client
):
    async def _fake_delete_model_version(model_name, version):
        raise DeletionRejected(f"version {version} is the current Production version")

    monkeypatch.setattr(
        model_routes, "delete_model_version", _fake_delete_model_version
    )

    response = client.delete("/v1/model/versions/1")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "is_production"


def test_delete_version_returns_404_for_an_unknown_version(monkeypatch, client):
    from mlflow.exceptions import MlflowException
    from mlflow.protos.databricks_pb2 import RESOURCE_DOES_NOT_EXIST

    async def _fake_delete_model_version(model_name, version):
        raise MlflowException("not found", error_code=RESOURCE_DOES_NOT_EXIST)

    monkeypatch.setattr(
        model_routes, "delete_model_version", _fake_delete_model_version
    )

    response = client.delete("/v1/model/versions/999")

    assert response.status_code == 404


def test_delete_version_returns_503_when_the_registry_is_unreachable(
    monkeypatch, client
):
    from mlflow.exceptions import MlflowException

    async def _fake_delete_model_version(model_name, version):
        raise MlflowException("API request failed with error code 403")

    monkeypatch.setattr(
        model_routes, "delete_model_version", _fake_delete_model_version
    )

    response = client.delete("/v1/model/versions/2")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "registry_unavailable"


def test_versions_returns_503_when_the_registry_is_unreachable(monkeypatch, client):
    from mlflow.exceptions import MlflowException

    async def _fake_list_versions(model_name):
        raise MlflowException("API request failed with error code 403")

    monkeypatch.setattr(model_routes, "list_versions", _fake_list_versions)

    response = client.get("/v1/model/versions")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "registry_unavailable"
