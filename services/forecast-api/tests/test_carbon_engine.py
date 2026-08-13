from __future__ import annotations

import pytest
import torch

from app.service.ml.carbon_engine import CarbonEngine


class TestCarbonEngine:
    def test_single_source_emissions_and_intensity_match_hand_calculation(self):
        # 1000 MW of a 500 gCO2e/kWh source for 0.5h (30-min interval):
        # energy = 1000 * 0.5 * 1000 = 500,000 kWh
        # emissions = 500,000 * 500 / 1000 = 250,000 kg
        engine = CarbonEngine(emission_factors={"coal": 500.0}, interval_hours=0.5)
        generation_mw = torch.tensor([[[[1000.0]]]])  # [B=1,H=1,S=1,Q=1]
        demand_mw = torch.tensor([[[1000.0]]])  # [1,1,1]

        result = engine.calculate(generation_mw, demand_mw)

        assert result["emissions_kg"].item() == pytest.approx(250_000.0, rel=1e-6)
        # carbon_intensity = emissions_g / demand_kWh = 250,000,000 / 500,000 = 500 g/kWh
        assert result["carbon_intensity"].item() == pytest.approx(500.0, rel=1e-6)

    def test_zero_carbon_source_produces_zero_emissions(self):
        engine = CarbonEngine(emission_factors={"wind": 0.0}, interval_hours=0.5)
        generation_mw = torch.tensor([[[[2000.0]]]])
        demand_mw = torch.tensor([[[2000.0]]])

        result = engine.calculate(generation_mw, demand_mw)

        assert result["emissions_kg"].item() == pytest.approx(0.0, abs=1e-9)
        assert result["carbon_intensity"].item() == pytest.approx(0.0, abs=1e-9)

    def test_mixed_sources_weight_by_generation_volume(self):
        # 1000 MW coal (910) + 1000 MW wind (4) for 1h
        engine = CarbonEngine(emission_factors={"coal": 910.0, "wind": 4.0}, interval_hours=1.0)
        generation_mw = torch.tensor([[[[1000.0], [1000.0]]]])  # [1,1,2,1]
        demand_mw = torch.tensor([[[2000.0]]])

        result = engine.calculate(generation_mw, demand_mw)

        # energy each = 1,000,000 kWh; emissions = (1e6*910 + 1e6*4)/1000 kg = 914,000 kg
        assert result["emissions_kg"].item() == pytest.approx(914_000.0, rel=1e-6)
        # intensity = total_g / demand_kWh = 914,000,000 / 2,000,000 = 457 g/kWh
        assert result["carbon_intensity"].item() == pytest.approx(457.0, rel=1e-6)

    def test_zero_demand_does_not_divide_by_zero(self):
        engine = CarbonEngine(emission_factors={"coal": 500.0}, interval_hours=0.5)
        generation_mw = torch.tensor([[[[100.0]]]])
        demand_mw = torch.tensor([[[0.0]]])

        result = engine.calculate(generation_mw, demand_mw)

        assert torch.isfinite(result["carbon_intensity"]).all()
