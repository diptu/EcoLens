"""Tests for ecolens.forecasting.service.carbon (root TODO.md's
"Deterministic Carbon Accounting").
"""

from __future__ import annotations

import pytest

from ecolens.forecasting.service.carbon import (
    EMISSION_FACTORS_KGCO2E_PER_MWH,
    RENEWABLE_FUELS,
    compute_carbon_metrics,
)
from ecolens.forecasting.service.normalization import GENERATION_COLUMNS


class TestEmissionFactors:
    def test_every_generation_column_has_a_factor(self):
        assert set(EMISSION_FACTORS_KGCO2E_PER_MWH) == set(GENERATION_COLUMNS)

    def test_all_factors_are_non_negative(self):
        assert all(v >= 0.0 for v in EMISSION_FACTORS_KGCO2E_PER_MWH.values())

    def test_coal_is_far_dirtier_than_wind(self):
        assert (
            EMISSION_FACTORS_KGCO2E_PER_MWH["coal_black_mw"]
            > EMISSION_FACTORS_KGCO2E_PER_MWH["wind_mw"] * 10
        )


class TestComputeCarbonMetrics:
    def test_all_coal_mix_has_the_coal_factor_as_intensity(self):
        mix = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        mix["coal_black_mw"] = 1000.0
        metrics = compute_carbon_metrics(mix)
        assert metrics.emissions_intensity_kgco2e_per_mwh == pytest.approx(
            EMISSION_FACTORS_KGCO2E_PER_MWH["coal_black_mw"]
        )
        assert metrics.renewable_proportion == 0.0

    def test_all_wind_mix_is_fully_renewable(self):
        mix = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        mix["wind_mw"] = 500.0
        metrics = compute_carbon_metrics(mix)
        assert metrics.renewable_proportion == pytest.approx(1.0)

    def test_pumped_hydro_is_not_counted_as_renewable(self):
        mix = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        mix["pumped_hydro_mw"] = 500.0
        metrics = compute_carbon_metrics(mix)
        assert metrics.renewable_proportion == 0.0

    def test_total_carbon_scales_with_interval_hours(self):
        mix = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        mix["gas_ccgt_mw"] = 1000.0
        half_hour = compute_carbon_metrics(mix, interval_hours=0.5)
        one_hour = compute_carbon_metrics(mix, interval_hours=1.0)
        assert one_hour.predicted_total_carbon_kgco2e == pytest.approx(
            half_hour.predicted_total_carbon_kgco2e * 2
        )

    def test_total_carbon_matches_hand_computed_value(self):
        mix = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        mix["coal_black_mw"] = 100.0
        mix["wind_mw"] = 100.0
        metrics = compute_carbon_metrics(mix, interval_hours=0.5)
        expected_rate = (
            100.0 * EMISSION_FACTORS_KGCO2E_PER_MWH["coal_black_mw"]
            + 100.0 * EMISSION_FACTORS_KGCO2E_PER_MWH["wind_mw"]
        )
        assert metrics.predicted_total_carbon_kgco2e == pytest.approx(
            expected_rate * 0.5
        )

    def test_zero_total_mix_returns_all_zero_metrics(self):
        mix = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        metrics = compute_carbon_metrics(mix)
        assert metrics.predicted_total_carbon_kgco2e == 0.0
        assert metrics.emissions_intensity_kgco2e_per_mwh == 0.0
        assert metrics.renewable_proportion == 0.0

    def test_negative_predictions_are_clipped_not_subtracted(self):
        mix = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        mix["coal_black_mw"] = 100.0
        mix["distillate_mw"] = -50.0  # a raw (un-rescaled) negative prediction
        metrics = compute_carbon_metrics(mix)
        # Should behave identically to distillate_mw simply being absent/0,
        # not as -50 MW of "negative emissions."
        mix_without_negative = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        mix_without_negative["coal_black_mw"] = 100.0
        expected = compute_carbon_metrics(mix_without_negative)
        assert metrics.predicted_total_carbon_kgco2e == pytest.approx(
            expected.predicted_total_carbon_kgco2e
        )

    def test_missing_keys_default_to_zero(self):
        metrics = compute_carbon_metrics({"coal_black_mw": 100.0})
        assert metrics.emissions_intensity_kgco2e_per_mwh == pytest.approx(
            EMISSION_FACTORS_KGCO2E_PER_MWH["coal_black_mw"]
        )

    def test_renewable_fuels_matches_fact_demand_30min_definition(self):
        # Regression guard: keep this in sync with fact_demand_30min.sql's
        # own renewable_generation_mw definition (hydro + wind +
        # solar_utility + solar_rooftop + biomass), not a second,
        # independently-drifting definition of "renewable."
        assert set(RENEWABLE_FUELS) == {
            "hydro_mw",
            "wind_mw",
            "solar_utility_mw",
            "solar_rooftop_mw",
            "biomass_mw",
        }
