"""Tests for the /metrics endpoint and its instrumentation (ECO-T02).

`REQUEST_LATENCY`/`CACHE_REQUESTS` are module-level (global-registry)
prometheus_client objects, shared across every test in this process --
that's normal for prometheus_client outside multiprocess mode, so
these assert presence/monotonic increase rather than exact counts.
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from conftest import FakeCache, FakeConnectionPool
from ecolens_forecast_api.app import create_app
from ecolens_forecast_api.metrics import CACHE_REQUESTS, REQUEST_LATENCY
from ecolens_forecast_api.settings import ForecastApiSettings
from test_routes import client_with_pool

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


def test_metrics_endpoint_is_public_and_well_formed():
    app = create_app(settings=ForecastApiSettings())
    with TestClient(app) as client:
        r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    # Metric families should be declared even before any traffic.
    assert "forecast_api_request_duration_seconds" in r.text
    assert "forecast_api_cache_requests_total" in r.text


def test_metrics_endpoint_does_not_require_api_key():
    app = create_app(settings=ForecastApiSettings(api_key="secret"))
    with TestClient(app) as client:
        r = client.get("/metrics")
    assert r.status_code == 200


def test_forecast_request_records_latency_for_its_region():
    pool = FakeConnectionPool(fetchrow_result=_feature_row())
    before = REQUEST_LATENCY.labels(region="QLD1")._sum.get()

    with client_with_pool(pool, FakeCache()) as client:
        r = client.get("/v1/forecast/QLD1")
    assert r.status_code == 200

    after = REQUEST_LATENCY.labels(region="QLD1")._sum.get()
    assert after > before


def test_cache_miss_then_hit_are_both_counted():
    cache = FakeCache(enabled=True)
    pool = FakeConnectionPool(fetchrow_result=_feature_row())
    miss_before = CACHE_REQUESTS.labels(result="miss")._value.get()
    hit_before = CACHE_REQUESTS.labels(result="hit")._value.get()

    with client_with_pool(pool, cache) as client:
        first = client.get("/v1/forecast/TAS1")
        second = client.get("/v1/forecast/TAS1")
    assert first.status_code == 200
    assert second.status_code == 200

    assert CACHE_REQUESTS.labels(result="miss")._value.get() == miss_before + 1
    assert CACHE_REQUESTS.labels(result="hit")._value.get() == hit_before + 1


def test_disabled_cache_is_counted_as_disabled_not_miss():
    cache = FakeCache(enabled=False)
    pool = FakeConnectionPool(fetchrow_result=_feature_row())
    disabled_before = CACHE_REQUESTS.labels(result="disabled")._value.get()

    with client_with_pool(pool, cache) as client:
        r = client.get("/v1/forecast/SA1")
    assert r.status_code == 200

    assert CACHE_REQUESTS.labels(result="disabled")._value.get() == disabled_before + 1
