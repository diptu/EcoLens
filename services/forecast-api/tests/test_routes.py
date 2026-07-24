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

import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime

import numpy as np
from fastapi.testclient import TestClient

from conftest import FakeCache, FakeConnectionPool
from ecolens_forecast_api.app import create_app
from ecolens_forecast_api.forecasting.features import FEATURE_COLUMNS, FeatureScaler
from ecolens_forecast_api.forecasting.loader import LoadedModel
from ecolens_forecast_api.forecasting.model import DemandLSTM
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


def _recent_rows(n: int = 48) -> list[dict]:
    rows = []
    for i in range(n):
        row = {"ts_30": datetime(2026, 1, 1, i // 2, 30 * (i % 2))}
        row.update({col: 0.0 for col in FEATURE_COLUMNS})
        row["demand_mw"] = 5000.0
        rows.append(row)
    return rows


def _fake_loaded_model(version: str = "1") -> LoadedModel:
    model = DemandLSTM(
        n_features=len(FEATURE_COLUMNS), hidden_size=4, num_layers=1, horizon=48
    )
    model.eval()
    scaler = FeatureScaler(
        mean=np.zeros(len(FEATURE_COLUMNS)),
        std=np.ones(len(FEATURE_COLUMNS)),
        columns=FEATURE_COLUMNS,
    )
    return LoadedModel(
        model=model, scaler=scaler, calibration=None, version=version, run_id="r1"
    )


@contextmanager
def client_with_pool(
    fake_pool: FakeConnectionPool | None = None,
    fake_cache: FakeCache | None = None,
    loaded_model: LoadedModel | None = None,
    **settings_kwargs,
):
    # Route tests fake the model/pool via `loaded_model`/`fake_pool` below
    # and are documented (module docstring) to "never touch a real
    # PostgreSQL or Redis server" -- but ForecastApiSettings picks up
    # `.env`'s FORECAST_MLFLOW_TRACKING_URI/FORECAST_PG_DSN by default,
    # which point at this repo's real local dev MLflow store and real
    # Neon Postgres DB. Left unoverridden, a test that means to simulate
    # "no model"/"no pool" (fake_pool=None, no loaded_model) instead
    # silently gets a real registered model or a real working DB
    # connection, which breaks the test's premise in confusing ways (a
    # stale model's scaler shape mismatching current FEATURE_COLUMNS; a
    # "no pool" test actually querying live data and getting 200 instead
    # of 503). Point both at guaranteed-empty/unreachable targets per
    # test instead, unless the test explicitly wants otherwise.
    settings_kwargs.setdefault(
        "mlflow_tracking_uri",
        f"sqlite:///{tempfile.gettempdir()}/forecast_api_test_isolation_{uuid.uuid4().hex}.db",
    )
    settings_kwargs.setdefault("pg_dsn", "postgresql://test:test@127.0.0.1:1/test")
    app = create_app(settings=ForecastApiSettings(**settings_kwargs))
    with TestClient(app) as c:
        if fake_pool is not None:
            app.state.pool = fake_pool
        if fake_cache is not None:
            app.state.cache = fake_cache
        if loaded_model is not None:
            app.state.reloader.state.current = loaded_model
        yield c


class TestHealth:
    def test_health_is_200_even_without_a_working_pool(self):
        with client_with_pool() as client:
            r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"status", "pg", "cache", "model", "uptime_seconds"}

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


class TestForecastWithRealModel:
    """ECO-F06: when a model is loaded and there's enough history, it
    serves the request instead of the baseline -- same response
    contract, different `model` field.
    """

    def test_uses_the_real_model_when_loaded_and_enough_history(self):
        pool = FakeConnectionPool(fetch_result=_recent_rows(48))
        loaded = _fake_loaded_model(version="7")
        with client_with_pool(pool, FakeCache(), loaded_model=loaded) as client:
            r = client.get("/v1/forecast/NSW1")
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "demand_lstm_v7"
        assert len(body["steps"]) == 48

    def test_falls_back_to_baseline_when_not_enough_history(self):
        # Real model is "loaded" but the mart only has 10 rows for this
        # region -- not enough for a lookback=48 window -- so this must
        # degrade to baseline rather than error.
        pool = FakeConnectionPool(
            fetch_result=_recent_rows(10), fetchrow_result=_feature_row()
        )
        loaded = _fake_loaded_model(version="7")
        with client_with_pool(pool, FakeCache(), loaded_model=loaded) as client:
            r = client.get("/v1/forecast/NSW1")
        assert r.status_code == 200
        assert r.json()["model"] == "seasonal_naive_v1"

    def test_no_model_loaded_uses_baseline(self):
        pool = FakeConnectionPool(fetchrow_result=_feature_row())
        with client_with_pool(pool, FakeCache()) as client:  # no loaded_model given
            r = client.get("/v1/forecast/NSW1")
        assert r.status_code == 200
        assert r.json()["model"] == "seasonal_naive_v1"

    def test_real_model_and_baseline_cache_under_different_keys(self):
        cache = FakeCache(enabled=True)
        pool = FakeConnectionPool(fetch_result=_recent_rows(48))
        loaded = _fake_loaded_model(version="7")
        with client_with_pool(pool, cache, loaded_model=loaded) as client:
            client.get("/v1/forecast/NSW1")
        assert "forecast:demand_lstm_v7:NSW1:48" in cache._store
        assert "forecast:seasonal_naive_v1:NSW1:48" not in cache._store


class TestHealthModelStatus:
    def test_reports_not_loaded_when_no_model(self):
        with client_with_pool() as client:
            r = client.get("/health")
        assert r.json()["model"]["loaded"] is False

    def test_reports_loaded_version(self):
        loaded = _fake_loaded_model(version="42")
        with client_with_pool(loaded_model=loaded) as client:
            r = client.get("/health")
        model_status = r.json()["model"]
        assert model_status["loaded"] is True
        assert model_status["version"] == "42"


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
