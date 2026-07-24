"""End-to-end route tests for the warehouse API.

Uses FastAPI's TestClient with `require_pool` overridden to a
FakeConnectionPool, so these never touch a real PostgreSQL server.
Dependency-resolution order matters here: `/regions/{region}/*` and
`/holidays/{year}` validate region/range/year via `Depends(...)`
declared *before* the pool dependency, so an invalid request 400s
without ever needing a working pool. `/features/*` (and the optional
`region` filter on `/holidays/{year}`) validate manually inside the
handler body, *after* the pool dependency has already resolved — so
those routes need a working pool override even for a request that
will ultimately 400.
"""

from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient

from conftest import FakeConnectionPool
from ecolens.warehouse.api.app import create_app
from ecolens.warehouse.api.dependencies import require_pool
from ecolens.warehouse.api.settings import WarehouseApiSettings

SINCE = "2026-01-01T00:00:00Z"
UNTIL = "2026-01-02T00:00:00Z"


@contextmanager
def client_with_pool(fake_pool: FakeConnectionPool | None = None, **settings_kwargs):
    app = create_app(settings=WarehouseApiSettings(**settings_kwargs))
    if fake_pool is not None:
        app.dependency_overrides[require_pool] = lambda: fake_pool
    with TestClient(app) as c:
        yield c


class TestHealth:
    def test_health_is_200_even_without_a_working_pool(self):
        with client_with_pool() as client:
            r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"status", "pg", "cache", "uptime_seconds"}

    def test_health_does_not_require_api_key(self):
        with client_with_pool(api_key="secret") as client:
            r = client.get("/health")
        assert r.status_code == 200


class TestRegions:
    def test_regions_happy_path(self):
        pool = FakeConnectionPool(
            fetch_result=[
                {"region": "NSW1", "state": "NSW", "population": None, "timezone": None}
            ]
        )
        with client_with_pool(pool) as client:
            r = client.get("/regions")
        assert r.status_code == 200
        assert r.json()[0]["region"] == "NSW1"

    def test_regions_503_without_pool(self):
        with client_with_pool(None) as client:
            r = client.get("/regions")
        assert r.status_code == 503


class TestRegionDemand:
    def test_invalid_region_400s_before_touching_pool(self):
        # No pool override at all -- proves validation short-circuits first.
        with client_with_pool(None) as client:
            r = client.get(
                "/regions/BOGUS/demand", params={"since": SINCE, "until": UNTIL}
            )
        assert r.status_code == 400

    def test_invalid_range_400s_before_touching_pool(self):
        with client_with_pool(None) as client:
            r = client.get(
                "/regions/NSW1/demand", params={"since": UNTIL, "until": SINCE}
            )
        assert r.status_code == 400

    def test_happy_path(self):
        pool = FakeConnectionPool(
            fetch_result=[{"ts": SINCE, "region": "NSW1", "demand_mw": 5000.0}]
        )
        with client_with_pool(pool) as client:
            r = client.get(
                "/regions/NSW1/demand", params={"since": SINCE, "until": UNTIL}
            )
        assert r.status_code == 200
        assert r.json()[0]["region"] == "NSW1"


class TestRegionSummary:
    def test_happy_path(self):
        pool = FakeConnectionPool(
            fetchrow_result={
                "n_obs": 48,
                "avg_demand_mw": 5000.0,
                "peak_demand_mw": 6000.0,
                "peak_ts": None,
                "min_demand_mw": 4000.0,
                "total_energy_mwh": 2400.0,
                "avg_price_mwh": 80.0,
                "avg_renewable_proportion": 30.0,
                "avg_temp_c": 22.0,
            }
        )
        with client_with_pool(pool) as client:
            r = client.get(
                "/regions/NSW1/summary", params={"since": SINCE, "until": UNTIL}
            )
        assert r.status_code == 200
        assert r.json()["n_obs"] == 48


class TestNationalDemand:
    def test_happy_path(self):
        pool = FakeConnectionPool(fetch_result=[{"ts_30": SINCE, "demand_mw": 25000.0}])
        with client_with_pool(pool) as client:
            r = client.get("/national/demand", params={"since": SINCE, "until": UNTIL})
        assert r.status_code == 200
        assert r.json()[0]["demand_mw"] == 25000.0


class TestFeatures:
    def test_v1_happy_path(self):
        pool = FakeConnectionPool(fetch_result=[{"ts_30": SINCE, "region": "NSW1"}])
        with client_with_pool(pool) as client:
            r = client.get(
                "/features/demand/v1",
                params={"region": "NSW1", "since": SINCE, "until": UNTIL},
            )
        assert r.status_code == 200

    def test_v1_invalid_region_400s(self):
        # Pool override still required: manual validation happens
        # after the pool dependency already resolved.
        pool = FakeConnectionPool(fetch_result=[])
        with client_with_pool(pool) as client:
            r = client.get(
                "/features/demand/v1",
                params={"region": "BOGUS", "since": SINCE, "until": UNTIL},
            )
        assert r.status_code == 400

    def test_latest_happy_path(self):
        pool = FakeConnectionPool(fetch_result=[{"ts_30": SINCE, "region": "NSW1"}])
        with client_with_pool(pool) as client:
            r = client.get("/features/demand/v1/latest", params={"region": "NSW1"})
        assert r.status_code == 200


class TestHolidays:
    def test_happy_path(self):
        pool = FakeConnectionPool(
            fetch_result=[
                {
                    "date": "2026-12-25",
                    "region": "NSW1",
                    "state": "NSW",
                    "holiday_name": "Christmas Day",
                    "holiday_type": "national",
                    "is_observed": False,
                    "days_until": 100,
                }
            ]
        )
        with client_with_pool(pool) as client:
            r = client.get("/holidays/2026")
        assert r.status_code == 200
        assert r.json()[0]["holiday_name"] == "Christmas Day"

    def test_invalid_year_400s_before_touching_pool(self):
        with client_with_pool(None) as client:
            r = client.get("/holidays/1500")
        assert r.status_code == 400

    def test_invalid_region_filter_400s(self):
        # Pool override still required (manual validation, same as /features).
        pool = FakeConnectionPool(fetch_result=[])
        with client_with_pool(pool) as client:
            r = client.get("/holidays/2026", params={"region": "BOGUS"})
        assert r.status_code == 400


class TestApiKey:
    def test_missing_key_401s_when_configured(self):
        pool = FakeConnectionPool(fetch_result=[])
        with client_with_pool(pool, api_key="secret") as client:
            r = client.get("/regions")
        assert r.status_code == 401

    def test_correct_key_passes(self):
        pool = FakeConnectionPool(fetch_result=[])
        with client_with_pool(pool, api_key="secret") as client:
            r = client.get("/regions", params={"api_key": "secret"})
        assert r.status_code == 200

    def test_no_key_required_when_unset(self):
        pool = FakeConnectionPool(fetch_result=[])
        with client_with_pool(pool) as client:
            r = client.get("/regions")
        assert r.status_code == 200
