"""Tests for ecolens_forecast_api.forecasting.fuel_forecast (root
TODO.md's "API & Registry Serving" -- turns the fuel ensemble's nowcast
into a forecast-horizon source breakdown, see that module's own docstring
for the "hold shares constant across the horizon" simplification).
"""

from __future__ import annotations

import pandas as pd
import pytest

from ecolens_forecast_api.forecasting.features import FEATURE_COLUMNS
from ecolens_forecast_api.forecasting.fuel_forecast import forecast_source_breakdown
from ecolens_forecast_api.forecasting.fuel_loader import LoadedFuelEnsemble
from ecolens_forecast_api.forecasting.normalization import GENERATION_COLUMNS


class _FakePyfuncModel:
    def __init__(self, prediction: dict[str, float]) -> None:
        self._prediction = prediction

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({fuel: [v] for fuel, v in self._prediction.items()})


def _feature_row() -> dict[str, float]:
    return {col: 1.0 for col in FEATURE_COLUMNS}


class TestForecastSourceBreakdown:
    def test_each_step_sums_to_its_own_p50(self):
        raw = {fuel: 10.0 for fuel in GENERATION_COLUMNS}
        loaded = LoadedFuelEnsemble(
            model=_FakePyfuncModel(raw), version="1", run_id="r1"
        )
        results = forecast_source_breakdown(
            loaded,
            _feature_row(),
            step_p50_values=[1000.0, 2000.0, 3000.0],
            interval_minutes=30,
        )
        assert len(results) == 3
        for (breakdown, carbon), expected_p50 in zip(
            results, [1000.0, 2000.0, 3000.0], strict=True
        ):
            assert breakdown is not None
            assert carbon is not None
            assert sum(breakdown.values()) == pytest.approx(expected_p50, rel=1e-6)

    def test_shares_are_constant_across_steps(self):
        raw = dict(zip(GENERATION_COLUMNS, range(1, len(GENERATION_COLUMNS) + 1)))
        loaded = LoadedFuelEnsemble(
            model=_FakePyfuncModel(raw), version="1", run_id="r1"
        )
        results = forecast_source_breakdown(
            loaded,
            _feature_row(),
            step_p50_values=[100.0, 200.0],
            interval_minutes=30,
        )
        breakdown_1, _ = results[0]
        breakdown_2, _ = results[1]
        fuel = GENERATION_COLUMNS[0]
        assert breakdown_1 is not None and breakdown_2 is not None
        share_1 = breakdown_1[fuel] / sum(breakdown_1.values())
        share_2 = breakdown_2[fuel] / sum(breakdown_2.values())
        assert share_1 == pytest.approx(share_2)

    def test_none_p50_produces_none_pair(self):
        raw = {fuel: 10.0 for fuel in GENERATION_COLUMNS}
        loaded = LoadedFuelEnsemble(
            model=_FakePyfuncModel(raw), version="1", run_id="r1"
        )
        results = forecast_source_breakdown(
            loaded, _feature_row(), step_p50_values=[None], interval_minutes=30
        )
        assert results == [(None, None)]
