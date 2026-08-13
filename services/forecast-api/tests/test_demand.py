from __future__ import annotations

from datetime import UTC, datetime

from app.main import app
from app.api.v1.deps import get_db, get_redis_client


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, row):
        self.row = row

    async def execute(self, query, params=None):
        return _FakeResult(self.row)


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


def test_summary_returns_renewable_share_and_price(client):
    row = {
        "total_generation_mw": 10_000.0,
        "total_renewable_mw": 3_860.0,
        "avg_price_mwh": 62.5,
    }
    app.dependency_overrides[get_db] = lambda: _FakeSession(row)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/demand/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["renewable_share_pct"] == 38.6
    assert body["avg_price_mwh"] == 62.5
    assert body["method"] == "mw_reading_ratio"
    assert body["since"].startswith(str(datetime.now(UTC).year))


def test_summary_accepts_explicit_period(client):
    row = {
        "total_generation_mw": 100.0,
        "total_renewable_mw": 50.0,
        "avg_price_mwh": 40.0,
    }
    app.dependency_overrides[get_db] = lambda: _FakeSession(row)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get(
            "/v1/demand/summary?since=2026-01-01T00:00:00Z&until=2026-02-01T00:00:00Z"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["since"] == "2026-01-01T00:00:00Z"
    assert body["until"] == "2026-02-01T00:00:00Z"
    assert body["renewable_share_pct"] == 50.0


def test_summary_404_when_no_data(client):
    app.dependency_overrides[get_db] = lambda: _FakeSession(None)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/demand/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_summary_result_is_cached(client):
    row = {
        "total_generation_mw": 10_000.0,
        "total_renewable_mw": 3_860.0,
        "avg_price_mwh": 62.5,
    }
    session = _FakeSession(row)
    redis = _FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis
    try:
        first = client.get("/v1/demand/summary")
        session.row = None  # would 404 if re-queried
        second = client.get("/v1/demand/summary")
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
