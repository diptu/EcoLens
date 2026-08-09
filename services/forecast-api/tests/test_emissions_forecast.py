from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler

from app.main import app
from app.api.v1.deps import get_db, get_model_registry, get_redis_client
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

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Handles the 3 query shapes an emissions-forecast request touches:
    `fct_energy_demand` (demand-forecast inference), `aemo_holidays`
    (also inference), and `fct_carbon_intensity` (current intensity)."""

    def __init__(self, demand_rows, intensity_row):
        self.demand_rows = demand_rows
        self.intensity_row = intensity_row

    async def execute(self, query, params=None):
        sql = str(query)
        if "fct_energy_demand" in sql:
            # Real per-region fetches (`data.load_latest_window`'s
            # cross-region-context fix) key off each row's `region`
            # matching the query's bound `:region` param -- retag the
            # fixture rows to that region rather than ignoring the
            # param, so a NEM request (5 regions) still sees every
            # region as having identical underlying data, same fixture
            # intent `test_forecast.py`'s identical fake session uses.
            rows = self.demand_rows
            if params and "region" in params:
                rows = [dict(r, region=params["region"]) for r in rows]
            return _FakeResult(rows)
        if "aemo_holidays" in sql:
            return _FakeResult([])
        if "fct_carbon_intensity" in sql:
            return _FakeResult([self.intensity_row] if self.intensity_row else [])
        raise AssertionError(f"unexpected query: {sql}")


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


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


def _build_bundle(lookback: int = 8, horizon: int = 4) -> object:
    from app.service.ml.features import FEATURE_COLUMNS, NUMERIC_COLUMNS

    n_features = len(FEATURE_COLUMNS)
    model = DemandLSTM(
        n_features=n_features, horizon=horizon, hidden_size=4, num_layers=1
    )
    model.eval()

    target_scaler = StandardScaler()
    target_scaler.fit(np.array([[4000.0], [5000.0], [6000.0]]))

    feature_scaler = StandardScaler()
    feature_scaler.fit(np.zeros((5, len(NUMERIC_COLUMNS))))

    calibration = ConformalCalibration(q=np.full(horizon, 50.0), alpha=0.2)

    class _Bundle:
        pass

    bundle = _Bundle()
    bundle.model = model
    bundle.feature_scalers = {
        r: feature_scaler for r in ("NSW1", "QLD1", "VIC1", "SA1", "TAS1")
    }
    bundle.target_scaler = target_scaler
    bundle.calibration = calibration
    bundle.version = "1"
    bundle.stage = "Production"
    bundle.run_id = "run-1"
    bundle.horizon = horizon
    bundle.lookback = lookback
    return bundle


_INTENSITY_ROW = {
    "hour": datetime(2026, 1, 1, 10, tzinfo=UTC),
    "region": "NSW1",
    "total_generation_mwh": 1000.0,
    "total_emissions_kgco2e": 446_000.0,
    "intensity_kgco2e_per_mwh": 446.0,
    "factors_version": "nger-2025-q4",
    "as_of": datetime(2026, 1, 1, 10, tzinfo=UTC),
}


def test_single_region_emissions_forecast_shape(client):
    bundle = _build_bundle(lookback=8, horizon=4)
    app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(bundle=bundle)
    app.dependency_overrides[get_db] = lambda: _FakeSession(
        demand_rows=_synthetic_rows(40), intensity_row=_INTENSITY_ROW
    )
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/forecast?region=NSW1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["region"] == "NSW1"
    assert body["intensity_kgco2e_per_mwh"] == pytest.approx(446.0, rel=1e-6)
    assert body["method"] == "demand_forecast_x_current_intensity"
    assert len(body["points"]) == 4
    for point in body["points"]:
        assert point["p10_kgco2e"] <= point["p50_kgco2e"] <= point["p90_kgco2e"]


def test_nem_emissions_forecast_defaults_to_nem(client):
    bundle = _build_bundle(lookback=8, horizon=4)
    app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(bundle=bundle)
    app.dependency_overrides[get_db] = lambda: _FakeSession(
        demand_rows=_synthetic_rows(40), intensity_row=_INTENSITY_ROW
    )
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/forecast")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.json()
    assert response.json()["region"] == "NEM"


def test_emissions_forecast_404_when_no_current_intensity(client):
    bundle = _build_bundle(lookback=8, horizon=4)
    app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(bundle=bundle)
    app.dependency_overrides[get_db] = lambda: _FakeSession(
        demand_rows=_synthetic_rows(40), intensity_row=None
    )
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions/forecast?region=NSW1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_emissions_forecast_503_when_no_model_loaded(client):
    app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(bundle=None)
    try:
        response = client.get("/v1/emissions/forecast?region=NSW1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_not_loaded"
