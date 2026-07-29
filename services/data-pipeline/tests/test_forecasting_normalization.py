"""Tests for ecolens.forecasting.service.normalization (root TODO.md's
"Normalization Constraint Layer").
"""

from __future__ import annotations

import pytest

from ecolens.forecasting.service.normalization import (
    GENERATION_COLUMNS,
    rescale_to_total,
)


class TestGenerationColumns:
    def test_excludes_battery_charge_and_curtailment(self):
        assert "battery_charge_mw" not in GENERATION_COLUMNS
        assert "curtailment_solar_utility_mw" not in GENERATION_COLUMNS
        assert "curtailment_wind_mw" not in GENERATION_COLUMNS

    def test_keeps_the_other_13_fuel_types(self):
        assert len(GENERATION_COLUMNS) == 13
        assert "coal_black_mw" in GENERATION_COLUMNS
        assert "battery_discharge_mw" in GENERATION_COLUMNS


class TestRescaleToTotal:
    def test_sums_exactly_to_target(self):
        raw = {fuel: 10.0 for fuel in GENERATION_COLUMNS}
        rescaled = rescale_to_total(raw, target_total=1000.0)
        assert sum(rescaled[f] for f in GENERATION_COLUMNS) == pytest.approx(1000.0)

    def test_preserves_relative_proportions(self):
        raw = dict(zip(GENERATION_COLUMNS, range(1, len(GENERATION_COLUMNS) + 1)))
        rescaled = rescale_to_total(raw, target_total=500.0)
        ratio = rescaled[GENERATION_COLUMNS[-1]] / rescaled[GENERATION_COLUMNS[0]]
        expected_ratio = raw[GENERATION_COLUMNS[-1]] / raw[GENERATION_COLUMNS[0]]
        assert ratio == pytest.approx(expected_ratio)

    def test_clips_negative_predictions_before_scaling(self):
        raw = {fuel: 10.0 for fuel in GENERATION_COLUMNS}
        raw[GENERATION_COLUMNS[0]] = -5.0
        rescaled = rescale_to_total(raw, target_total=100.0)
        assert rescaled[GENERATION_COLUMNS[0]] == 0.0
        assert sum(rescaled[f] for f in GENERATION_COLUMNS) == pytest.approx(100.0)
        assert all(v >= 0.0 for v in rescaled.values())

    def test_all_zero_raw_and_zero_target_returns_all_zero(self):
        raw = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        rescaled = rescale_to_total(raw, target_total=0.0)
        assert all(v == 0.0 for v in rescaled.values())

    def test_all_zero_raw_but_nonzero_target_falls_back_to_equal_split(self):
        raw = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        rescaled = rescale_to_total(raw, target_total=260.0)
        assert sum(rescaled[f] for f in GENERATION_COLUMNS) == pytest.approx(260.0)
        expected_share = 260.0 / len(GENERATION_COLUMNS)
        assert all(v == pytest.approx(expected_share) for v in rescaled.values())

    def test_excluded_keys_pass_through_at_zero_not_kept_at_raw_value(self):
        raw = {fuel: 10.0 for fuel in GENERATION_COLUMNS}
        raw["battery_charge_mw"] = -40.0
        raw["curtailment_wind_mw"] = 25.0
        rescaled = rescale_to_total(raw, target_total=130.0)
        assert rescaled["battery_charge_mw"] == 0.0
        assert rescaled["curtailment_wind_mw"] == 0.0
        assert sum(rescaled[f] for f in GENERATION_COLUMNS) == pytest.approx(130.0)

    def test_missing_keys_default_to_zero_before_clipping(self):
        raw = {GENERATION_COLUMNS[0]: 10.0}  # every other GENERATION_COLUMNS key absent
        rescaled = rescale_to_total(raw, target_total=50.0)
        assert rescaled[GENERATION_COLUMNS[0]] == pytest.approx(50.0)
        assert all(rescaled[f] == 0.0 for f in GENERATION_COLUMNS[1:])
