from __future__ import annotations

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


def _body(**overrides):
    body = {
        "region": "NSW1",
        "kwh": 420,
        "period": "2026-07-01T00:00Z/2026-07-31T23:59Z",
    }
    body.update(overrides)
    return body


class TestFootprintCalculation:
    def test_matches_readmes_documented_example(self, client):
        # README.md's own example: 420 kWh at intensity 446 kgCO2e/MWh (=
        # 0.446 kgCO2e/kWh) -> 187.32 kgCO2e.
        row = {
            "total_generation_mwh": 1000.0,
            "total_emissions_kgco2e": 446000.0,
            "factors_version": "nger-2025-q4",
        }
        app.dependency_overrides[get_db] = lambda: _FakeSession(row)
        app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
        try:
            response = client.post("/v1/footprint", json=_body())
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["intensity_kg_co2e_per_kwh"] == 0.446
        assert body["kg_co2e"] == 187.32
        assert body["factors_version"] == "nger-2025-q4"

    def test_404_when_no_data_for_period(self, client):
        app.dependency_overrides[get_db] = lambda: _FakeSession(None)
        app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
        try:
            response = client.post("/v1/footprint", json=_body())
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404


class TestPeriodParsing:
    def test_malformed_period_is_400(self, client):
        app.dependency_overrides[get_db] = lambda: _FakeSession(None)
        app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
        try:
            response = client.post("/v1/footprint", json=_body(period="not-a-period"))
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_period"

    def test_start_after_end_is_400(self, client):
        app.dependency_overrides[get_db] = lambda: _FakeSession(None)
        app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
        try:
            response = client.post(
                "/v1/footprint",
                json=_body(period="2026-07-31T23:59Z/2026-07-01T00:00Z"),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_period"
