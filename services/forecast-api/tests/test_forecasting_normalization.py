"""Tests for ecolens_forecast_api.forecasting.normalization -- structural
duplicate of data-pipeline's service/normalization.py, see that module's
own docstring for the full rescale-math reasoning.
"""

from __future__ import annotations

import pytest

from ecolens_forecast_api.forecasting.normalization import (
    FUEL_COLUMNS,
    GENERATION_COLUMNS,
    rescale_to_total,
)


class TestFuelColumns:
    def test_has_16_entries(self):
        assert len(FUEL_COLUMNS) == 16

    def test_generation_columns_excludes_charge_and_curtailment(self):
        assert len(GENERATION_COLUMNS) == 13
        assert "battery_charge_mw" not in GENERATION_COLUMNS
        assert "curtailment_solar_utility_mw" not in GENERATION_COLUMNS
        assert "curtailment_wind_mw" not in GENERATION_COLUMNS


class TestRescaleToTotal:
    def test_sums_to_target(self):
        raw = {fuel: 5.0 for fuel in GENERATION_COLUMNS}
        rescaled = rescale_to_total(raw, target_total=260.0)
        assert sum(rescaled[f] for f in GENERATION_COLUMNS) == pytest.approx(260.0)

    def test_shares_sum_to_one_when_target_is_one(self):
        raw = dict(zip(GENERATION_COLUMNS, range(1, len(GENERATION_COLUMNS) + 1)))
        shares = rescale_to_total(raw, target_total=1.0)
        assert sum(shares[f] for f in GENERATION_COLUMNS) == pytest.approx(1.0)

    def test_negative_predictions_clipped(self):
        raw = {fuel: 10.0 for fuel in GENERATION_COLUMNS}
        raw[GENERATION_COLUMNS[0]] = -3.0
        rescaled = rescale_to_total(raw, target_total=100.0)
        assert rescaled[GENERATION_COLUMNS[0]] == 0.0

    def test_all_zero_target_returns_all_zero(self):
        raw = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        rescaled = rescale_to_total(raw, target_total=0.0)
        assert all(v == 0.0 for v in rescaled.values())
