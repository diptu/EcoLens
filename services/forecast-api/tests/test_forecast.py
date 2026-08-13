from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler

from app.main import app
from app.api.v1.deps import get_db, get_model_registry, get_redis_client
from app.service.ml.bias_correction import DemandBiasCorrection
from app.service.ml.conformal import ConformalCalibration
from app.service.ml.data import _TRAINING_COLUMNS
from app.models.ml import DemandLSTM


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, demand_rows):
        self.demand_rows = demand_rows

    async def execute(self, query, params=None):
        sql = str(query)
        if "fct_energy_demand" in sql:
            # Real per-region fetches (`data.load_latest_window`'s own
            # cross-region-context fix) key off each row's `region`
            # field matching the query's bound `:region` param -- retag
            # the fixture rows to that region rather than ignoring the
            # param outright, so a multi-region caller (the NEM
            # aggregate tests below) still sees every region as having
            # identical underlying data, the actual test intent, instead
            # of every fetch silently returning rows tagged for whichever
            # region happened to build the fixture.
            rows = self.demand_rows
            if params and "region" in params:
                rows = [dict(r, region=params["region"]) for r in rows]
            return _FakeResult(rows)
        if "aemo_holidays" in sql:
            return _FakeResult([])
        raise AssertionError(f"unexpected query: {sql}")


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)

    async def expire(self, key, seconds):
        pass


class _FakeRegistry:
    def __init__(self, bundle):
        self.bundle = bundle


def _synthetic_rows(n: int, region: str = "NSW1") -> list[dict]:
    ts = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(0)
    rows = []
    for i in range(n):
        rows.append(
            dict(
                zip(
                    _TRAINING_COLUMNS,
                    [
                        ts[i],
                        region,
                        5000.0 + 100 * np.sin(i / 10) + rng.normal(0, 5),
                        50.0,
                        5500.0,
                        1500.0,
                        20.0,
                        21.0,
                        50.0,
                        10.0,
                    ],
                    strict=True,
                )
            )
        )
    return rows


def _build_bundle(lookback: int = 8, horizon: int = 4) -> tuple:
    from app.service.ml.features import FEATURE_COLUMNS

    n_features = len(FEATURE_COLUMNS)
    model = DemandLSTM(
        n_features=n_features, horizon=horizon, hidden_size=4, num_layers=1
    )
    model.eval()

    from app.service.ml.features import NUMERIC_COLUMNS

    target_scaler = StandardScaler()
    target_scaler.fit(np.array([[4000.0], [5000.0], [6000.0]]))

    # The real scaler is only ever fit on `NUMERIC_COLUMNS` (a subset of
    # `FEATURE_COLUMNS`, data-pipeline's `ml/data.py`'s `fit_scalers`) --
    # matching that shape here (not `n_features`) is what a real
    # end-to-end run against Postgres+MLflow caught this test's earlier
    # version getting wrong (it fit on `n_features` instead, matching the
    # router's now-fixed bug rather than the real contract).
    feature_scaler = StandardScaler()
    feature_scaler.fit(np.zeros((5, len(NUMERIC_COLUMNS))))

    calibration = ConformalCalibration(q=np.full(horizon, 50.0), alpha=0.2)

    class _Bundle:
        pass

    bundle = _Bundle()
    bundle.model = model
    bundle.feature_scalers = {"NSW1": feature_scaler}
    bundle.target_scaler = target_scaler
    bundle.calibration = calibration
    bundle.bias_correction = DemandBiasCorrection()
    bundle.version = "1"
    bundle.stage = "Production"
    bundle.run_id = "run-1"
    bundle.horizon = horizon
    bundle.lookback = lookback
    return bundle


class TestForecastEndpoint:
    def test_503_when_no_model_loaded(self, client):
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=None
        )
        try:
            response = client.get("/v1/forecast?region=NSW1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "model_not_loaded"

    def test_503_when_not_enough_recent_data(self, client):
        bundle = _build_bundle(lookback=8, horizon=4)
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=bundle
        )
        app.dependency_overrides[get_db] = lambda: _FakeSession(
            demand_rows=_synthetic_rows(5)
        )
        app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
        try:
            response = client.get("/v1/forecast?region=NSW1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "insufficient_data"

    def test_503_when_no_scaler_for_region(self, client):
        bundle = _build_bundle(lookback=8, horizon=4)
        bundle.feature_scalers = {}  # no region fitted
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=bundle
        )
        app.dependency_overrides[get_db] = lambda: _FakeSession(
            demand_rows=_synthetic_rows(40)
        )
        app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
        try:
            response = client.get("/v1/forecast?region=NSW1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "model_not_trained_for_region"

    def test_returns_a_real_forecast_shape(self, client):
        bundle = _build_bundle(lookback=8, horizon=4)
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=bundle
        )
        app.dependency_overrides[get_db] = lambda: _FakeSession(
            demand_rows=_synthetic_rows(40)
        )
        app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
        try:
            response = client.get("/v1/forecast?region=NSW1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["region"] == "NSW1"
        assert body["model"] == "lstm_demand@production"
        assert body["interval"] == "5m"
        assert body["horizon"] == "20m"  # 4 native steps @ 5min
        assert len(body["points"]) == 4
        for point in body["points"]:
            assert point["p10"] <= point["p50"] <= point["p90"]
            assert point["unit"] == "MW"

    def test_result_is_cached_per_model_version(self, client):
        bundle = _build_bundle(lookback=8, horizon=4)
        redis = _FakeRedis()
        session = _FakeSession(demand_rows=_synthetic_rows(40))
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=bundle
        )
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_redis_client] = lambda: redis
        try:
            first = client.get("/v1/forecast?region=NSW1")
            session.demand_rows = []  # would 503 if re-queried
            second = client.get("/v1/forecast?region=NSW1")
        finally:
            app.dependency_overrides.clear()

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()

    def test_nem_aggregate_sums_the_5_nem_regions(self, client):
        bundle = _build_bundle(lookback=8, horizon=4)
        # Fake session ignores the bound `:region` param and always
        # returns the same synthetic rows, so every NEM region infers
        # identically here -- the aggregate should come out to exactly
        # 5x a single region's forecast.
        bundle.feature_scalers = {
            r: bundle.feature_scalers["NSW1"]
            for r in ("NSW1", "QLD1", "VIC1", "SA1", "TAS1")
        }
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=bundle
        )
        app.dependency_overrides[get_db] = lambda: _FakeSession(
            demand_rows=_synthetic_rows(40)
        )
        app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
        try:
            single = client.get("/v1/forecast?region=NSW1")
            nem = client.get("/v1/forecast?region=NEM")
        finally:
            app.dependency_overrides.clear()

        assert single.status_code == nem.status_code == 200
        single_body, nem_body = single.json(), nem.json()
        assert nem_body["region"] == "NEM"
        assert nem_body["interval"] == single_body["interval"]
        assert nem_body["horizon"] == single_body["horizon"]
        assert len(nem_body["points"]) == len(single_body["points"])
        for np_point, sp_point in zip(
            nem_body["points"], single_body["points"], strict=True
        ):
            assert np_point["p50"] == pytest.approx(sp_point["p50"] * 5, abs=1.0)
            assert np_point["p10"] <= np_point["p50"] <= np_point["p90"]

    def test_nem_aggregate_result_is_cached_separately(self, client):
        bundle = _build_bundle(lookback=8, horizon=4)
        bundle.feature_scalers = {
            r: bundle.feature_scalers["NSW1"]
            for r in ("NSW1", "QLD1", "VIC1", "SA1", "TAS1")
        }
        redis = _FakeRedis()
        session = _FakeSession(demand_rows=_synthetic_rows(40))
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=bundle
        )
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_redis_client] = lambda: redis
        try:
            first = client.get("/v1/forecast?region=NEM")
            session.demand_rows = []  # would 503 if re-queried
            second = client.get("/v1/forecast?region=NEM")
        finally:
            app.dependency_overrides.clear()

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()

    def test_records_the_shortest_horizon_point_for_reconciliation(self, client):
        """`TODO.md` Forecasting Phase 4's fallback mechanism -- a real
        (non-fallback) response logs its first point to Redis so
        `service/ml/forecast_reconciliation.py`'s background sweep can
        later compare it against real demand."""
        bundle = _build_bundle(lookback=8, horizon=4)
        redis = _FakeRedis()
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=bundle
        )
        app.dependency_overrides[get_db] = lambda: _FakeSession(
            demand_rows=_synthetic_rows(40)
        )
        app.dependency_overrides[get_redis_client] = lambda: redis
        try:
            response = client.get("/v1/forecast?region=NSW1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        first_point = response.json()["points"][0]
        served_key = "forecast_served:lstm_demand:NSW1"
        assert served_key in redis.hashes
        (recorded,) = redis.hashes[served_key].values()
        recorded_payload = json.loads(recorded)
        assert recorded_payload["p50_mw"] == pytest.approx(first_point["p50"])

    def test_serves_the_baseline_when_the_circuit_breaker_is_open(self, client):
        """Same `TODO.md` item -- once the forecast-quality breaker for
        `(model, region)` is open, `GET /v1/forecast` must serve the
        seasonal-naive baseline instead of the real model, and say so
        honestly via `served_by`."""
        bundle = _build_bundle(lookback=8, horizon=4)
        redis = _FakeRedis()
        # Simulates an open breaker -- same key shape
        # `ForecastCircuitBreaker`'s own `_opened_at_key` builds.
        redis.store["forecast_circuit_breaker:lstm_demand:NSW1:opened_at"] = str(
            time.time()
        )
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=bundle
        )
        app.dependency_overrides[get_db] = lambda: _FakeSession(
            demand_rows=_synthetic_rows(2500)
        )
        app.dependency_overrides[get_redis_client] = lambda: redis
        try:
            response = client.get("/v1/forecast?region=NSW1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["served_by"] == "baseline_fallback"
        assert body["model"] == "seasonal_naive"
        assert len(body["points"]) == bundle.horizon
        # A fallback response must never be logged for reconciliation --
        # there'd be nothing meaningful to reconcile a baseline against
        # itself for.
        assert redis.hashes == {}

    def test_applies_the_adaptive_calibration_scale_to_the_served_interval(self, client):
        """`TODO.md` Forecasting Phase 4's "widen or tighten uncertainty
        bounds" item -- a non-default `adaptive_calibration.py` scale
        already stored for `(model, region)` must actually widen (or
        narrow) what `GET /v1/forecast` serves, not just sit unused in
        Redis."""
        redis = _FakeRedis()
        # One bundle (one randomly-initialized model), reused for both
        # requests -- comparing two *separately* constructed bundles
        # would compare two different random weight initializations, not
        # the effect of the scale. Mutating `bundle.version` between the
        # two calls (rather than the scale, which isn't part of the
        # cache key at all) is what keeps the second request from
        # hitting the first's cached response.
        bundle = _build_bundle(lookback=8, horizon=4)
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=bundle
        )
        app.dependency_overrides[get_db] = lambda: _FakeSession(
            demand_rows=_synthetic_rows(40)
        )
        app.dependency_overrides[get_redis_client] = lambda: redis
        try:
            bundle.version = "1"
            unscaled_response = client.get("/v1/forecast?region=NSW1")

            redis.store["forecast_calibration_scale:lstm_demand:NSW1"] = "2.0"
            bundle.version = "2"
            scaled_response = client.get("/v1/forecast?region=NSW1")
        finally:
            app.dependency_overrides.clear()

        assert unscaled_response.status_code == scaled_response.status_code == 200
        unscaled_point = unscaled_response.json()["points"][0]
        scaled_point = scaled_response.json()["points"][0]
        # p50 (the point estimate) is untouched by the scale -- only the
        # interval around it widens.
        unscaled_half_width = unscaled_point["p50"] - unscaled_point["p10"]
        scaled_half_width = scaled_point["p50"] - scaled_point["p10"]
        # `abs=1.0`, not a tight `rel` tolerance -- `_build_response`
        # rounds `p10`/`p50`/`p90` to 1 decimal *independently*, so two
        # half-widths each built from independently-rounded numbers can
        # legitimately differ from an exact 2x relationship by a couple
        # tenths of a MW even when the underlying scale really is applied.
        assert scaled_half_width == pytest.approx(unscaled_half_width * 2.0, abs=1.0)
