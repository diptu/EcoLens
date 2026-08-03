from __future__ import annotations

from datetime import UTC, datetime

from app.main import app
from app.api.v1.deps import get_model_registry


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
