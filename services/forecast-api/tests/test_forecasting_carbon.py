"""Tests for ecolens_forecast_api.forecasting.carbon -- structural
duplicate of data-pipeline's forecasting/service/carbon.py, see that
module's own docstring for the emission-factor sourcing rationale.
"""

from __future__ import annotations

import pytest

from ecolens_forecast_api.forecasting.carbon import (
    EMISSION_FACTORS_KGCO2E_PER_MWH,
    compute_carbon_metrics,
)
from ecolens_forecast_api.forecasting.normalization import GENERATION_COLUMNS


class TestEmissionFactors:
    def test_every_generation_column_has_a_factor(self):
        assert set(EMISSION_FACTORS_KGCO2E_PER_MWH) == set(GENERATION_COLUMNS)


class TestComputeCarbonMetrics:
    def test_all_wind_is_fully_renewable_and_low_intensity(self):
        mix = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        mix["wind_mw"] = 200.0
        metrics = compute_carbon_metrics(mix)
        assert metrics.renewable_proportion == pytest.approx(1.0)
        assert metrics.emissions_intensity_kgco2e_per_mwh == pytest.approx(
            EMISSION_FACTORS_KGCO2E_PER_MWH["wind_mw"]
        )

    def test_zero_mix_returns_zero_metrics(self):
        mix = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        metrics = compute_carbon_metrics(mix)
        assert metrics.predicted_total_carbon_kgco2e == 0.0
        assert metrics.emissions_intensity_kgco2e_per_mwh == 0.0
        assert metrics.renewable_proportion == 0.0

    def test_total_carbon_scales_with_interval_hours(self):
        mix = dict.fromkeys(GENERATION_COLUMNS, 0.0)
        mix["coal_black_mw"] = 500.0
        half = compute_carbon_metrics(mix, interval_hours=0.5)
        full = compute_carbon_metrics(mix, interval_hours=1.0)
        assert full.predicted_total_carbon_kgco2e == pytest.approx(
            half.predicted_total_carbon_kgco2e * 2
        )
