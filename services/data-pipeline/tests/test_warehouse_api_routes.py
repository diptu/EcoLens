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

import pytest
from fastapi.testclient import TestClient

from conftest import FakeConnectionPool
from ecolens.warehouse.api.v1.app import create_app
from ecolens.warehouse.api.v1.read_dependencies import require_pool
from ecolens.warehouse.core.api_settings import WarehouseApiSettings

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
        # Without an explicit, guaranteed-to-fail target here, the real
        # app lifespan's pool.connect() would use whatever WAREHOUSE_PG_DSN
        # happens to be set in the ambient .env -- which is a real,
        # working NeonDB connection in this repo's dev environment, so
        # the "without pool" scenario silently stopped reproducing.
        # pg_dsn=None clears that env-sourced DSN; localhost:1 is
        # guaranteed nothing is listening, so connect() fails fast.
        with client_with_pool(
            None, pg_dsn=None, pg_host="127.0.0.1", pg_port=1
        ) as client:
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


class TestNationalSummary:
    def test_happy_path(self):
        pool = FakeConnectionPool(
            fetchrow_result={
                "n_slots": 48,
                "avg_demand_mw": 25000.0,
                "peak_demand_mw": 30000.0,
                "peak_ts": None,
                "min_demand_mw": 20000.0,
                "total_energy_mwh": 1_200_000.0,
                "avg_renewable_proportion": 25.0,
                "avg_emissions_intensity_kgco2e_per_mwh": 700.0,
                "total_carbon_tco2e": 840.0,
            }
        )
        with client_with_pool(pool) as client:
            r = client.get("/national/summary", params={"since": SINCE, "until": UNTIL})
        assert r.status_code == 200
        assert r.json()["total_carbon_tco2e"] == 840.0

    def test_invalid_range_400s_before_touching_pool(self):
        with client_with_pool(None) as client:
            r = client.get("/national/summary", params={"since": UNTIL, "until": SINCE})
        assert r.status_code == 400


class TestNationalDailyEmissions:
    def test_happy_path(self):
        pool = FakeConnectionPool(
            fetch_result=[
                {
                    "date_local": "2026-01-01",
                    "total_demand_mwh": 500_000.0,
                    "avg_renewable_proportion": 20.0,
                    "avg_emissions_intensity_kgco2e_per_mwh": 700.0,
                    "total_carbon_tco2e": 350_000.0,
                }
            ]
        )
        with client_with_pool(pool) as client:
            r = client.get(
                "/national/emissions/daily", params={"since": SINCE, "limit": 7}
            )
        assert r.status_code == 200
        assert r.json()[0]["total_carbon_tco2e"] == 350_000.0


class TestNationalGenerationMix:
    def test_happy_path(self):
        pool = FakeConnectionPool(
            fetchrow_result={
                "coal_black_mw": 100.0,
                "coal_brown_mw": 0.0,
                "gas_ccgt_mw": 0.0,
                "gas_ocgt_mw": 0.0,
                "gas_other_mw": 0.0,
                "hydro_mw": 0.0,
                "pumped_hydro_mw": 0.0,
                "wind_mw": 100.0,
                "solar_utility_mw": 0.0,
                "solar_rooftop_mw": 0.0,
                "biomass_mw": 0.0,
                "distillate_mw": 0.0,
                "battery_discharge_mw": 0.0,
            }
        )
        with client_with_pool(pool) as client:
            r = client.get(
                "/national/generation-mix", params={"since": SINCE, "until": UNTIL}
            )
        assert r.status_code == 200
        body = r.json()
        assert body["total_mw"] == 200.0
        assert body["mix_share"]["coal_black_mw"] == pytest.approx(0.5)

    def test_invalid_range_400s_before_touching_pool(self):
        with client_with_pool(None) as client:
            r = client.get(
                "/national/generation-mix", params={"since": UNTIL, "until": SINCE}
            )
        assert r.status_code == 400


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
            ],
            fetchval_result=1,
        )
        with client_with_pool(pool) as client:
            r = client.get("/holidays/2026")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["limit"] == 100
        assert body["offset"] == 0
        assert body["items"][0]["holiday_name"] == "Christmas Day"

    def test_pagination_params_are_passed_through(self):
        pool = FakeConnectionPool(fetch_result=[], fetchval_result=0)
        with client_with_pool(pool) as client:
            r = client.get("/holidays/2026", params={"limit": 10, "offset": 20})
        assert r.status_code == 200
        body = r.json()
        assert body["limit"] == 10
        assert body["offset"] == 20
        # fetchval (count) then fetch (page) -- both get the paging args.
        fetch_call = next(c for c in pool.calls if c[0] == "fetch")
        assert fetch_call[2][-2:] == (10, 20)

    def test_invalid_year_400s_before_touching_pool(self):
        with client_with_pool(None) as client:
            r = client.get("/holidays/1500")
        assert r.status_code == 400

    def test_invalid_region_filter_400s(self):
        # Pool override still required (manual validation, same as /features).
        pool = FakeConnectionPool(fetch_result=[], fetchval_result=0)
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


_KPI_ROW = {
    "total_carbon_tco2e": 840.0,
    "avg_emissions_intensity_kgco2e_per_mwh": 700.0,
    "avg_renewable_proportion": 25.0,
    "total_energy_mwh": 1_200_000.0,
}


class TestExecutiveKpisHappyPath:
    def test_default_params_returns_200_with_six_kpis(self):
        pool = FakeConnectionPool(fetchrow_result=_KPI_ROW, fetch_result=[])
        with client_with_pool(pool) as client:
            r = client.get("/api/analytics/executive-kpis")
        assert r.status_code == 200
        body = r.json()
        assert len(body["kpis"]) == 6
        assert body["meta"]["period"] == "ytd"
        assert body["meta"]["region"] == "NEM"
        assert body["meta"]["currency"] == "AUD"

    def test_explicit_query_params_are_echoed_in_meta(self):
        pool = FakeConnectionPool(fetchrow_result=_KPI_ROW, fetch_result=[])
        with client_with_pool(pool) as client:
            r = client.get(
                "/api/analytics/executive-kpis",
                params={"period": "30d", "region": "VIC1", "currency": "USD"},
            )
        assert r.status_code == 200
        meta = r.json()["meta"]
        assert meta == {**meta, "period": "30d", "region": "VIC1", "currency": "USD"}

    def test_response_headers(self):
        pool = FakeConnectionPool(fetchrow_result=_KPI_ROW, fetch_result=[])
        with client_with_pool(pool) as client:
            r = client.get(
                "/api/analytics/executive-kpis",
                headers={"X-Request-Id": "abc-123"},
            )
        assert r.headers["Cache-Control"] == "private, max-age=60"
        assert r.headers["X-Cache"] == "MISS"
        assert r.headers["X-Request-Id"] == "abc-123"

    def test_no_request_id_header_when_not_supplied(self):
        pool = FakeConnectionPool(fetchrow_result=_KPI_ROW, fetch_result=[])
        with client_with_pool(pool) as client:
            r = client.get("/api/analytics/executive-kpis")
        assert "X-Request-Id" not in r.headers


class TestExecutiveKpisValidation:
    def test_invalid_period_400s_before_touching_pool(self):
        with client_with_pool(None) as client:
            r = client.get("/api/analytics/executive-kpis", params={"period": "bogus"})
        assert r.status_code == 400

    def test_invalid_region_400s_before_touching_pool(self):
        with client_with_pool(None) as client:
            r = client.get("/api/analytics/executive-kpis", params={"region": "BOGUS"})
        assert r.status_code == 400

    def test_invalid_currency_400s_before_touching_pool(self):
        with client_with_pool(None) as client:
            r = client.get("/api/analytics/executive-kpis", params={"currency": "GBP"})
        assert r.status_code == 400


class TestExecutiveKpisPoolAndAuth:
    def test_503_without_a_working_pool(self):
        with client_with_pool(
            None, pg_dsn=None, pg_host="127.0.0.1", pg_port=1
        ) as client:
            r = client.get("/api/analytics/executive-kpis")
        assert r.status_code == 503

    def test_missing_api_key_401s_when_configured(self):
        pool = FakeConnectionPool(fetchrow_result=_KPI_ROW, fetch_result=[])
        with client_with_pool(pool, api_key="secret") as client:
            r = client.get("/api/analytics/executive-kpis")
        assert r.status_code == 401

    def test_correct_api_key_passes(self):
        pool = FakeConnectionPool(fetchrow_result=_KPI_ROW, fetch_result=[])
        with client_with_pool(pool, api_key="secret") as client:
            r = client.get(
                "/api/analytics/executive-kpis", params={"api_key": "secret"}
            )
        assert r.status_code == 200
