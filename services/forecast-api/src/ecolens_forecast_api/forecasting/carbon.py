"""Structural duplicate of data-pipeline's `forecasting/service/carbon.py`
-- same rationale as `normalization.py` in this package: pure deterministic
math, no reason to depend on the other package's `ecolens` import path to
get it. See that module's docstring for the full sourcing rationale
(IPCC AR5 lifecycle medians + AEMO NGA-consistent combustion factors).
Keep these two files' constants in sync by hand if either changes --
there's no shared package boundary to enforce it automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

from .normalization import GENERATION_COLUMNS

EMISSION_FACTORS_KGCO2E_PER_MWH: dict[str, float] = {
    "coal_black_mw": 900.0,
    "coal_brown_mw": 1300.0,
    "gas_ccgt_mw": 420.0,
    "gas_ocgt_mw": 680.0,
    "gas_other_mw": 550.0,
    "hydro_mw": 24.0,
    "pumped_hydro_mw": 24.0,
    "wind_mw": 11.0,
    "solar_utility_mw": 48.0,
    "solar_rooftop_mw": 41.0,
    "biomass_mw": 230.0,
    "distillate_mw": 800.0,
    "battery_discharge_mw": 0.0,
}

_missing_factors = [
    f for f in GENERATION_COLUMNS if f not in EMISSION_FACTORS_KGCO2E_PER_MWH
]
if _missing_factors:
    raise AssertionError(
        f"EMISSION_FACTORS_KGCO2E_PER_MWH is missing entries for: {_missing_factors}"
    )

RENEWABLE_FUELS: tuple[str, ...] = (
    "hydro_mw",
    "wind_mw",
    "solar_utility_mw",
    "solar_rooftop_mw",
    "biomass_mw",
)


@dataclass(frozen=True)
class CarbonMetrics:
    predicted_total_carbon_kgco2e: float
    emissions_intensity_kgco2e_per_mwh: float
    renewable_proportion: float


def compute_carbon_metrics(
    fuel_mix_mw: dict[str, float], *, interval_hours: float = 0.5
) -> CarbonMetrics:
    total_mw = sum(max(0.0, fuel_mix_mw.get(fuel, 0.0)) for fuel in GENERATION_COLUMNS)

    if total_mw <= 1e-9:
        return CarbonMetrics(
            predicted_total_carbon_kgco2e=0.0,
            emissions_intensity_kgco2e_per_mwh=0.0,
            renewable_proportion=0.0,
        )

    weighted_kgco2e_per_hour = sum(
        max(0.0, fuel_mix_mw.get(fuel, 0.0)) * EMISSION_FACTORS_KGCO2E_PER_MWH[fuel]
        for fuel in GENERATION_COLUMNS
    )
    intensity = weighted_kgco2e_per_hour / total_mw
    renewable_mw = sum(max(0.0, fuel_mix_mw.get(fuel, 0.0)) for fuel in RENEWABLE_FUELS)

    return CarbonMetrics(
        predicted_total_carbon_kgco2e=weighted_kgco2e_per_hour * interval_hours,
        emissions_intensity_kgco2e_per_mwh=intensity,
        renewable_proportion=renewable_mw / total_mw,
    )


__all__ = [
    "EMISSION_FACTORS_KGCO2E_PER_MWH",
    "RENEWABLE_FUELS",
    "CarbonMetrics",
    "compute_carbon_metrics",
]
