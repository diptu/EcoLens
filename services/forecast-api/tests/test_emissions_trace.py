from __future__ import annotations

from datetime import UTC, datetime

from app.main import app
from app.api.v1.deps import get_db, get_redis_client


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


class _TwoQuerySession:
    """`load_emissions_trace` issues exactly two queries in a fixed
    order (intensity rows, then mix rows for that hour range) -- this
    fake returns each list in turn rather than the same result for
    every call, unlike the single-query `_FakeSession` the sibling
    emissions tests use."""

    def __init__(self, intensity_rows, mix_rows):
        self.intensity_rows = intensity_rows
        self.mix_rows = mix_rows
        self.calls: list[tuple[str, dict | None]] = []

    async def execute(self, query, params=None):
        self.calls.append((str(query), params))
        if len(self.calls) == 1:
            return _FakeResult(self.intensity_rows)
        return _FakeResult(self.mix_rows)


HOUR_1 = datetime(2026, 1, 1, 10, tzinfo=UTC)
HOUR_2 = datetime(2026, 1, 1, 9, tzinfo=UTC)

INTENSITY_ROWS = [
    {
        "hour": HOUR_1,
        "total_generation_mwh": 1000.0,
        "total_emissions_kgco2e": 446_000.0,
        "intensity_kgco2e_per_mwh": 446.0,
        "factors_version": "nger-2025-q4",
    },
    {
        "hour": HOUR_2,
        "total_generation_mwh": 900.0,
        "total_emissions_kgco2e": 410_000.0,
        "intensity_kgco2e_per_mwh": 455.5,
        "factors_version": "nger-2025-q4",
    },
]

MIX_ROWS = [
    {
        "hour": HOUR_1,
        "fuel_type": "coal_black",
        "total_generation_mwh": 600.0,
        "total_emissions_kgco2e": 396_000.0,
    },
    {
        "hour": HOUR_1,
        "fuel_type": "wind",
        "total_generation_mwh": 400.0,
        "total_emissions_kgco2e": 50_000.0,
    },
    {
        "hour": HOUR_2,
        "fuel_type": "coal_black",
        "total_generation_mwh": 900.0,
        "total_emissions_kgco2e": 410_000.0,
    },
]


def test_returns_intervals_with_per_fuel_breakdown(client):
    session = _TwoQuerySession(INTENSITY_ROWS, MIX_ROWS)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/trace?region=NSW1&limit=2")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["region"] == "NSW1"
    assert len(body["intervals"]) == 2

    first = body["intervals"][0]
    assert first["intensity_kgco2e_per_mwh"] == 446.0
    assert len(first["by_fuel"]) == 2
    coal = next(f for f in first["by_fuel"] if f["fuel_type"] == "coal_black")
    assert coal["generation_mwh"] == 600.0
    assert coal["emissions_kgco2e"] == 396_000.0
    assert coal["effective_factor_kgco2e_per_mwh"] == 396_000.0 / 600.0

    second = body["intervals"][1]
    assert second["intensity_kgco2e_per_mwh"] == 455.5
    assert len(second["by_fuel"]) == 1


def test_the_two_queries_scope_the_mix_query_to_the_intensity_rows_hour_range(client):
    session = _TwoQuerySession(INTENSITY_ROWS, MIX_ROWS)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        client.get("/v1/emissions/trace?region=NSW1&limit=2")
    finally:
        app.dependency_overrides.clear()

    assert len(session.calls) == 2
    _, intensity_params = session.calls[0]
    assert intensity_params["region"] == "NSW1"
    assert intensity_params["limit"] == 2

    mix_sql, mix_params = session.calls[1]
    assert "fct_generation_mix" in mix_sql
    assert mix_params["min_hour"] == HOUR_2
    assert mix_params["max_hour"] == HOUR_1


def test_404_when_no_data_for_region(client):
    session = _TwoQuerySession([], [])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/trace?region=NSW1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_an_hour_with_no_matching_mix_rows_gets_an_empty_by_fuel_list(client):
    session = _TwoQuerySession(INTENSITY_ROWS, [])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/trace?region=NSW1&limit=2")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    for interval in response.json()["intervals"]:
        assert interval["by_fuel"] == []


def test_result_is_cached(client):
    session = _TwoQuerySession(INTENSITY_ROWS, MIX_ROWS)
    redis = _FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis
    try:
        first = client.get("/v1/emissions/trace?region=NSW1&limit=2")
        session.intensity_rows = []  # would 404 if re-queried
        second = client.get("/v1/emissions/trace?region=NSW1&limit=2")
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_limit_out_of_range_is_422(client):
    session = _TwoQuerySession([], [])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/trace?region=NSW1&limit=0")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
