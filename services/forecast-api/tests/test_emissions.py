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

    def all(self):
        return self._row if self._row is not None else []


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


def test_returns_latest_intensity(client):
    row = {
        "hour": datetime(2026, 1, 1, 10, tzinfo=UTC),
        "region": "NSW1",
        "total_generation_mwh": 1000.0,
        "total_emissions_kgco2e": 446000.0,
        "intensity_kgco2e_per_mwh": 446.0,
        "factors_version": "nger-2025-q4",
    }
    app.dependency_overrides[get_db] = lambda: _FakeSession(row)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions?region=NSW1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["region"] == "NSW1"
    assert body["intensity_kgco2e_per_mwh"] == 446.0
    assert body["method"] == "live_mix_weighted"
    assert body["factors_version"] == "nger-2025-q4"


def test_404_when_no_data_for_region(client):
    app.dependency_overrides[get_db] = lambda: _FakeSession(None)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions?region=NSW1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_result_is_cached(client):
    row = {
        "hour": datetime(2026, 1, 1, 10, tzinfo=UTC),
        "region": "NSW1",
        "total_generation_mwh": 1000.0,
        "total_emissions_kgco2e": 446000.0,
        "intensity_kgco2e_per_mwh": 446.0,
        "factors_version": "nger-2025-q4",
    }
    session = _FakeSession(row)
    redis = _FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis
    try:
        first = client.get("/v1/emissions?region=NSW1")
        session.row = None  # would 404 if re-queried
        second = client.get("/v1/emissions?region=NSW1")
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_current_returns_all_region_rollup(client):
    row = {
        "as_of": datetime(2026, 1, 5, 10, tzinfo=UTC),
        "total_generation_mwh": 950.0,
        "total_emissions_kgco2e": 420_000.0,
        "factors_version": "nger-2025-q4",
    }
    app.dependency_overrides[get_db] = lambda: _FakeSession(row)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/current")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total_emissions_kgco2e"] == 420_000.0
    assert body["intensity_kgco2e_per_mwh"] == 420_000.0 / 950.0
    assert body["method"] == "live_mix_weighted"
    assert body["factors_version"] == "nger-2025-q4"


def test_current_404_when_no_data(client):
    app.dependency_overrides[get_db] = lambda: _FakeSession(None)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/current")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_current_result_is_cached(client):
    row = {
        "as_of": datetime(2026, 1, 5, 10, tzinfo=UTC),
        "total_generation_mwh": 950.0,
        "total_emissions_kgco2e": 420_000.0,
        "factors_version": "nger-2025-q4",
    }
    session = _FakeSession(row)
    redis = _FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis
    try:
        first = client.get("/v1/emissions/current")
        session.row = None  # would 404 if re-queried
        second = client.get("/v1/emissions/current")
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_timeseries_returns_bucketed_points(client):
    rows = [
        {
            "bucket": datetime(2026, 1, 1, tzinfo=UTC),
            "total_generation_mwh": 1000.0,
            "total_emissions_kgco2e": 500_000.0,
            "intensity_kgco2e_per_mwh": 500.0,
            "factors_version": "nger-2025-q4",
        },
        {
            "bucket": datetime(2026, 1, 2, tzinfo=UTC),
            "total_generation_mwh": 1100.0,
            "total_emissions_kgco2e": 550_000.0,
            "intensity_kgco2e_per_mwh": 500.0,
            "factors_version": "nger-2025-q4",
        },
    ]
    app.dependency_overrides[get_db] = lambda: _FakeSession(rows)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/timeseries?bucket=day&days=8")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["bucket"] == "day"
    assert len(body["points"]) == 2
    assert body["points"][0]["total_emissions_kgco2e"] == 500_000.0
    assert body["points"][1]["intensity_kgco2e_per_mwh"] == 500.0


def test_timeseries_empty_is_not_an_error(client):
    app.dependency_overrides[get_db] = lambda: _FakeSession([])
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/timeseries?bucket=hour&days=1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["points"] == []


def test_timeseries_rejects_invalid_bucket(client):
    app.dependency_overrides[get_db] = lambda: _FakeSession([])
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/timeseries?bucket=week")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


class _RecordingSession:
    """Captures the executed SQL/params so tests can assert the region
    filter is actually applied (or omitted), not just that the response
    shape looks right."""

    def __init__(self, rows):
        self.rows = rows
        self.last_sql: str | None = None
        self.last_params: dict | None = None

    async def execute(self, query, params=None):
        self.last_sql = str(query)
        self.last_params = params
        return _FakeResult(self.rows)


def test_timeseries_with_region_filters_query_and_echoes_region(client):
    session = _RecordingSession([])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/timeseries?bucket=day&days=8&region=NSW1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["region"] == "NSW1"
    assert session.last_sql is not None and "region = :region" in session.last_sql
    assert session.last_params["region"] == "NSW1"


def test_timeseries_without_region_omits_region_filter(client):
    session = _RecordingSession([])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/timeseries?bucket=day&days=8")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["region"] is None
    assert session.last_sql is not None and "region = :region" not in session.last_sql


def test_ytd_returns_all_region_rollup(client):
    row = {
        "total_generation_mwh": 205_000_000.0,
        "total_emissions_kgco2e": 12_840_000_000.0,
        "factors_version": "nger-2025-q4",
    }
    app.dependency_overrides[get_db] = lambda: _FakeSession(row)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/ytd")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total_emissions_kgco2e"] == 12_840_000_000.0
    assert body["total_emissions_tco2e"] == 12_840_000.0
    assert body["method"] == "live_mix_weighted"
    assert body["factors_version"] == "nger-2025-q4"
    assert body["since"].startswith(str(datetime.now(UTC).year))


def test_ytd_404_when_no_data(client):
    app.dependency_overrides[get_db] = lambda: _FakeSession(None)
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/ytd")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_ytd_result_is_cached(client):
    row = {
        "total_generation_mwh": 205_000_000.0,
        "total_emissions_kgco2e": 12_840_000_000.0,
        "factors_version": "nger-2025-q4",
    }
    session = _FakeSession(row)
    redis = _FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis
    try:
        first = client.get("/v1/emissions/ytd")
        session.row = None  # would 404 if re-queried
        second = client.get("/v1/emissions/ytd")
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
