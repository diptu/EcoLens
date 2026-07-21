"""End-to-end route tests for forecast-api.

Uses FastAPI's TestClient with `app.state.pool`/`app.state.cache`
swapped for fakes *after* the lifespan has run (the forecast route
reads `require_pool(request)` directly rather than via `Depends`, so
a cache hit can return before ever needing a working pool -- see
`routes.py`'s docstring -- which means `app.dependency_overrides`
can't intercept it; state-swapping is the only way to fake it here),
so these never touch a real PostgreSQL or Redis server.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from fastapi.testclient import TestClient

from conftest import FakeCache, FakeConnectionPool
from ecolens_forecast_api.app import create_app
from ecolens_forecast_api.settings import ForecastApiSettings

BASE_TS = "2026-07-21T12:00:00+00:00"


def _feature_row(**overrides):
    row = {
        "ts_30": datetime.fromisoformat(BASE_TS),
        "demand_mw": 5000.0,
        "demand_rolling_std_7d": 100.0,
    }
    row.update({f"demand_lag_{k:02d}": 5000.0 - 10 * k for k in range(1, 49)})
    row.update(overrides)
    return row


@contextmanager
def client_with_pool(
    fake_pool: FakeConnectionPool | None = None,
    fake_cache: FakeCache | None = None,
    **settings_kwargs,
):
    app = create_app(settings=ForecastApiSettings(**settings_kwargs))
    with TestClient(app) as c:
        if fake_pool is not None:
            app.state.pool = fake_pool
        if fake_cache is not None:
            app.state.cache = fake_cache
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


class TestForecast:
    def test_happy_path(self):
        pool = FakeConnectionPool(fetchrow_result=_feature_row())
        with client_with_pool(pool, FakeCache()) as client:
            r = client.get("/v1/forecast/NSW1")
        assert r.status_code == 200
        body = r.json()
        assert body["region"] == "NSW1"
        assert body["model"] == "seasonal_naive_v1"
        assert len(body["steps"]) == 48
        assert body["steps"][-1]["p50"] == 5000.0

    def test_horizon_query_param_limits_steps(self):
        pool = FakeConnectionPool(fetchrow_result=_feature_row())
        with client_with_pool(pool, FakeCache()) as client:
            r = client.get("/v1/forecast/NSW1", params={"horizon": 5})
        assert r.status_code == 200
        assert len(r.json()["steps"]) == 5

    def test_invalid_region_400s_before_touching_pool(self):
        with client_with_pool(None) as client:
            r = client.get("/v1/forecast/BOGUS")
        assert r.status_code == 400

    def test_invalid_horizon_400s(self):
        pool = FakeConnectionPool(fetchrow_result=_feature_row())
        with client_with_pool(pool, FakeCache()) as client:
            r = client.get("/v1/forecast/NSW1", params={"horizon": 100})
        assert r.status_code == 400

    def test_503_without_pool(self):
        with client_with_pool(None) as client:
            r = client.get("/v1/forecast/NSW1")
        assert r.status_code == 503

    def test_404_when_no_feature_data_yet(self):
        pool = FakeConnectionPool(fetchrow_result=None)
        with client_with_pool(pool, FakeCache()) as client:
            r = client.get("/v1/forecast/NSW1")
        assert r.status_code == 404

    def test_cache_hit_skips_the_pool(self):
        cached_response = {
            "region": "NSW1",
            "generated_at": BASE_TS,
            "as_of": BASE_TS,
            "model": "seasonal_naive_v1",
            "interval_minutes": 30,
            "steps": [],
        }
        cache = FakeCache(enabled=True)
        cache._store["forecast:seasonal_naive_v1:NSW1:48"] = cached_response
        # No pool override at all -- proves the cache hit short-circuits
        # before `require_pool` would ever 503.
        with client_with_pool(None, cache) as client:
            r = client.get("/v1/forecast/NSW1")
        assert r.status_code == 200
        assert r.json()["steps"] == []


class TestApiKey:
    def test_missing_key_401s_when_configured(self):
        pool = FakeConnectionPool(fetchrow_result=_feature_row())
        with client_with_pool(pool, FakeCache(), api_key="secret") as client:
            r = client.get("/v1/forecast/NSW1")
        assert r.status_code == 401

    def test_correct_key_passes(self):
        pool = FakeConnectionPool(fetchrow_result=_feature_row())
        with client_with_pool(pool, FakeCache(), api_key="secret") as client:
            r = client.get("/v1/forecast/NSW1", params={"api_key": "secret"})
        assert r.status_code == 200
