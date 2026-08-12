"""`POST /v1/model/train`/`GET /v1/model/training-runs` -- ported from
data-pipeline's identical `tests/test_model_router.py`'s train/
training-runs sections (the version-listing/promote/delete sections of
that file test endpoints that already existed here before the training-
code migration and already have their own coverage in this service)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.api.v1.deps import get_db, get_redis_client
from app.main import app
from app.service.model import actions


class _FakeRedis:
    """Same fake `test_forecast.py` already uses for its own cached
    endpoints -- `GET /v1/model/training-runs` gained real inline
    caching 2026-08-11, so its tests need the same per-test-isolated
    fake the rest of this codebase's cached-endpoint tests already rely
    on, not the real shared local Redis (which would otherwise leak a
    cached response across these tests, and hit a real network client
    tied to a since-closed event loop between tests)."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, anomalies_count=0):
        self._anomalies_count = anomalies_count

    async def execute(self, query, params=None):
        return _FakeResult((self._anomalies_count,))


class _FakeSessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def fake_training_trigger_deps(monkeypatch):
    """Publishing a real training-trigger event does a real DB query
    (anomaly count) and a real RabbitMQ publish -- fake both. Patches
    `app.service.model.actions`'s own module-level names (that module
    imports `get_session`/`publish_training_trigger_event` directly),
    same pattern data-pipeline's identical test used against its
    `flows` module."""
    published: list[dict] = []

    async def fake_publish(payload):
        published.append(payload)

    monkeypatch.setattr(actions, "get_session", lambda: _FakeSessionCtx(_FakeSession()))
    monkeypatch.setattr(actions, "publish_training_trigger_event", fake_publish)
    return published


def test_train_endpoint_publishes_a_training_trigger_event(client):
    response = client.post("/v1/model/train", json={})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["triggered_by"] == "public"
    assert body["regions"]  # falls back to Settings.model_default_regions
    assert body["window_since"] < body["window_until"]


def test_train_endpoint_accepts_explicit_regions_and_window(
    client, fake_training_trigger_deps
):
    response = client.post(
        "/v1/model/train", json={"regions": ["QLD1"], "window_hours": 6}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["regions"] == ["QLD1"]
    assert len(fake_training_trigger_deps) == 1
    assert fake_training_trigger_deps[0]["regions"] == ["QLD1"]


def test_train_endpoint_defaults_architecture_to_lstm(
    client, fake_training_trigger_deps
):
    response = client.post("/v1/model/train", json={})

    assert response.status_code == 202
    assert response.json()["architecture"] == "lstm"
    assert fake_training_trigger_deps[0]["architecture"] == "lstm"


@pytest.mark.parametrize("architecture", ["lstm", "tft", "timesfm_correction"])
def test_train_endpoint_threads_the_requested_architecture_through(
    client, fake_training_trigger_deps, architecture
):
    """2026-08-11 fix: this endpoint used to hardcode `"architecture":
    "lstm"` in the published event regardless of what the caller asked
    for -- selecting TFT or TimesFM in the dashboard's Fine-tune form and
    submitting silently fine-tuned LSTM instead. Confirms all three
    architectures the product description names (LSTM, TFT, TimesFM) now
    actually reach the published training-trigger event."""
    response = client.post(
        "/v1/model/train", json={"regions": ["QLD1"], "architecture": architecture}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["architecture"] == architecture
    assert fake_training_trigger_deps[0]["architecture"] == architecture


def test_train_endpoint_defaults_full_retrain_to_false(client, fake_training_trigger_deps):
    response = client.post("/v1/model/train", json={})

    assert response.status_code == 202
    assert response.json()["full_retrain"] is False
    assert fake_training_trigger_deps[0]["full_retrain"] is False


def test_train_endpoint_threads_full_retrain_through(client, fake_training_trigger_deps):
    """2026-08-11, real feature: the dashboard's "Train a new version"
    tab previously had no trigger endpoint at all (a disabled preview
    button). Confirms `full_retrain: true` reaches the published
    training-trigger event, which is what `training_worker.
    handle_training_trigger` dispatches on to pick the real from-scratch
    trainer over the incremental one."""
    response = client.post(
        "/v1/model/train", json={"regions": ["QLD1"], "full_retrain": True}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["full_retrain"] is True
    assert fake_training_trigger_deps[0]["full_retrain"] is True


def test_train_endpoint_rejects_an_unknown_architecture(client):
    response = client.post(
        "/v1/model/train", json={"architecture": "some_other_model"}
    )

    assert response.status_code == 422


def test_train_endpoint_requires_no_auth(client):
    # Deliberately open, same reasoning as data-pipeline's identical
    # endpoint had -- this asserts the *absence* of a role gate, not a
    # specific role.
    response = client.post("/v1/model/train", json={})

    assert response.status_code != 401
    assert response.status_code != 403


class _FakeQueryResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeDbSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, query, params=None):
        return _FakeQueryResult(self._rows)


def _training_log_row(**overrides):
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "model_name": "lstm_demand",
        "status": "running",
        "triggered_by": "manual",
        "regions": ["NSW1"],
        "window_start": datetime(2026, 8, 1, tzinfo=UTC),
        "window_end": datetime(2026, 8, 2, tzinfo=UTC),
        "started_at": datetime(2026, 8, 2, tzinfo=UTC),
        "finished_at": None,
        "run_id": None,
        "model_version": None,
        "error_message": None,
    }
    row.update(overrides)
    return row


def test_training_runs_returns_real_rows(client):
    app.dependency_overrides[get_db] = lambda: _FakeDbSession([_training_log_row()])
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/model/training-runs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["status"] == "running"
    assert body["data"][0]["regions"] == ["NSW1"]
    assert body["data"][0]["triggered_by"] == "manual"


def test_training_runs_normalises_regions_when_the_driver_returns_a_json_string(
    client,
):
    # asyncpg/SQLAlchemy usually hand back jsonb already parsed, but a
    # raw text() query doesn't guarantee it -- confirm the string path
    # gets decoded too, not just the already-a-list happy path above.
    app.dependency_overrides[get_db] = lambda: _FakeDbSession(
        [_training_log_row(regions='["QLD1", "VIC1"]')]
    )
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/model/training-runs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"][0]["regions"] == ["QLD1", "VIC1"]


def test_training_runs_empty_before_any_training_has_ever_run(client):
    app.dependency_overrides[get_db] = lambda: _FakeDbSession([])
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/model/training-runs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"] == []
