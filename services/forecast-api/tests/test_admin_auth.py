"""Admin-token gate (`app/core/security.py`) on model write routes, and
the public cooldown on `POST /v1/model/train`."""

from __future__ import annotations

import pytest

from app.api.v1.deps import get_redis_client
from app.core.config import get_settings
from app.main import app
from app.service.model import actions

from tests.conftest import TEST_ADMIN_TOKEN
from tests.test_model_train_routes import _FakeSession, _FakeSessionCtx

GATED = [
    ("post", "/v1/model/tune"),
    ("post", "/v1/model/versions/import"),
    ("post", "/v1/model/versions/import-onnx"),
    ("post", "/v1/model/versions/1/evaluate"),
    ("post", "/v1/model/versions/1/promote"),
    ("delete", "/v1/model/versions/1"),
]


@pytest.mark.parametrize(("method", "path"), GATED)
def test_gated_route_rejects_a_missing_token(anon_client, method, path):
    response = getattr(anon_client, method)(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(("method", "path"), GATED)
def test_gated_route_rejects_a_wrong_token(anon_client, method, path):
    response = getattr(anon_client, method)(path, headers={"X-Admin-Token": "nope"})

    assert response.status_code == 401


def test_gated_route_accepts_a_bearer_token(anon_client):
    # Gets past the gate to the handler's own validation (no body -> 422).
    response = anon_client.post(
        "/v1/model/versions/import",
        headers={"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"},
    )

    assert response.status_code == 422


def test_gated_route_fails_closed_when_no_token_is_configured(anon_client, monkeypatch):
    monkeypatch.delenv("ADMIN_API_TOKEN")
    get_settings.cache_clear()

    response = anon_client.post(
        "/v1/model/versions/1/promote", headers={"X-Admin-Token": "anything"}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "admin_disabled"


class _NxRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


@pytest.fixture
def fake_trigger(monkeypatch):
    published: list[dict] = []

    async def fake_publish(payload):
        published.append(payload)

    monkeypatch.setattr(actions, "publish_training_trigger_event", fake_publish)
    monkeypatch.setattr(actions, "get_session", lambda: _FakeSessionCtx(_FakeSession()))
    redis = _NxRedis()
    app.dependency_overrides[get_redis_client] = lambda: redis
    yield published
    app.dependency_overrides.clear()


def test_public_train_is_limited_to_one_job_per_cooldown(anon_client, fake_trigger):
    first = anon_client.post("/v1/model/train", json={})
    second = anon_client.post("/v1/model/train", json={})

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "train_cooldown"
    assert len(fake_trigger) == 1


def test_admin_train_bypasses_the_cooldown(anon_client, fake_trigger):
    headers = {"X-Admin-Token": TEST_ADMIN_TOKEN}
    anon_client.post("/v1/model/train", json={})

    response = anon_client.post("/v1/model/train", json={}, headers=headers)

    assert response.status_code == 202
    assert len(fake_trigger) == 2
