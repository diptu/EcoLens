from __future__ import annotations

from app.main import app
from app.api.v1.deps import get_db, get_redis_client


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, query, params=None):
        return _FakeResult(self.rows)


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


_ROWS = [
    {
        "fuel_type": "wind",
        "category": "renewable",
        "is_renewable": True,
        "total_generation_mwh": 300.0,
        "total_emissions_kgco2e": 3_000.0,
    },
    {
        "fuel_type": "coal",
        "category": "fossil",
        "is_renewable": False,
        "total_generation_mwh": 700.0,
        "total_emissions_kgco2e": 574_000.0,
    },
]


def test_returns_fuel_breakdown_with_percentages(client):
    app.dependency_overrides[get_db] = lambda: _FakeSession(_ROWS)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/generation-mix")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total_generation_mwh"] == 1000.0
    assert body["total_emissions_kgco2e"] == 577_000.0
    assert len(body["items"]) == 2
    wind = next(i for i in body["items"] if i["fuel_type"] == "wind")
    coal = next(i for i in body["items"] if i["fuel_type"] == "coal")
    assert wind["pct_of_total_generation"] == 30.0
    assert coal["pct_of_total_generation"] == 70.0
    assert wind["is_renewable"] is True
    assert coal["category"] == "fossil"


def test_region_filter_is_echoed(client):
    app.dependency_overrides[get_db] = lambda: _FakeSession(_ROWS)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/generation-mix?region=NSW1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["region"] == "NSW1"


def test_404_when_no_rows(client):
    app.dependency_overrides[get_db] = lambda: _FakeSession([])
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/generation-mix")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_result_is_cached(client):
    session = _FakeSession(_ROWS)
    redis = _FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis
    try:
        first = client.get("/v1/generation-mix")
        session.rows = []  # would 404 if re-queried
        second = client.get("/v1/generation-mix")
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
