"""Root TODO.md's "Deterministic Carbon Accounting": "Compute carbon
metrics deterministically -- no ML in this path. predicted_total_carbon_kgco2e,
emissions intensity, and renewable proportion should all be derived
straight from the fuel mix using IPCC AR5 and AEMO NGES emission factors,
not predicted by a model."

Pure functions, no I/O, no model inference -- this module's only inputs
are a fuel-mix MW dict (from `service/normalization.py`'s rescaled
per-fuel breakdown, or any other source) and a time interval; nothing
here calls a database, a registry, or a trained model. `fact_demand_30min`
already carries an `emissions_intensity_kgco2e_per_mwh` column, but that's
an *observed* value straight from the upstream APIs for *past* timestamps
-- there's no equivalent for a *forecast* horizon, where only a predicted
fuel mix exists. This module is what turns that predicted mix into the
same kind of number for the future.

Emission factors (`EMISSION_FACTORS_KGCO2E_PER_MWH`) are IPCC AR5 (2014
Working Group III, Annex III, Table A.III.2) lifecycle-median gCO2e/kWh
figures for the renewable/storage fuel types (hydro, wind, solar, biomass
-- IPCC's own harmonized median across reviewed studies), blended with
combustion-based figures broadly consistent with AEMO's own published
Carbon Dioxide Equivalent Intensity Index and Australia's NGA (National
Greenhouse Accounts) Scheme factors for black/brown coal and gas
generation, which run meaningfully higher than IPCC's global lifecycle
medians for those fuels (Australian black coal plant is disproportionately
older/less efficient than the global fleet IPCC's medians are drawn from,
and brown coal -- Latrobe Valley lignite -- is among the most emissions-
intensive generation in the world). These are reasonable, publicly-
grounded planning-level constants, not a state-by-state, quarter-by-
quarter calibration against AEMO's exact published NGA figures -- a good
future refinement if source-exact precision starts to matter more than
"deterministic and directionally correct."
"""

from __future__ import annotations

from dataclasses import dataclass

from ecolens.forecasting.service.normalization import GENERATION_COLUMNS

# kg CO2-e per MWh generated, by fuel type -- see module docstring for
# sourcing. Every `GENERATION_COLUMNS` entry must have one (enforced
# below at import time), so a future fuel added to that tuple can't
# silently default to "zero emissions" here.
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
    # Batteries have no direct combustion emissions at discharge -- the
    # emissions from whatever generation charged them are already
    # attributed via that source's own factor above (when it was
    # generated, not when it's later released back to the grid).
    # Attributing round-trip storage losses/charge-time source mix
    # precisely is a real refinement this simplification skips.
    "battery_discharge_mw": 0.0,
}

_missing_factors = [
    f for f in GENERATION_COLUMNS if f not in EMISSION_FACTORS_KGCO2E_PER_MWH
]
if _missing_factors:
    raise AssertionError(
        f"EMISSION_FACTORS_KGCO2E_PER_MWH is missing entries for: {_missing_factors} "
        "-- every service.normalization.GENERATION_COLUMNS fuel must have a factor"
    )

# Same 5 fuels `fact_demand_30min.sql`'s own `renewable_generation_mw`
# sums (hydro + wind + solar_utility + solar_rooftop + biomass) -- kept
# consistent with that mart's definition rather than inventing a second
# one (e.g. pumped_hydro and battery_discharge are deliberately excluded
# there too: storage, not primary renewable generation).
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
    """`fuel_mix_mw`: MW per fuel type over the interval (typically
    `normalization.rescale_to_total`'s output, already summing to a
    known total demand/generation) -- only `GENERATION_COLUMNS` keys
    contribute; anything else present is ignored, same "only true
    generation counts toward the total" reasoning `normalization.py`
    documents.

    `interval_hours` converts the instantaneous MW mix into energy
    (MWh) for `predicted_total_carbon_kgco2e` -- 0.5 matches this repo's
    30-min grain everywhere else (`fact_demand_30min`, `FEATURE_COLUMNS`
    lag/rolling windows, ...); `emissions_intensity_kgco2e_per_mwh` and
    `renewable_proportion` are both MW-ratio quantities and don't depend
    on it.
    """
    total_mw = sum(max(0.0, fuel_mix_mw.get(fuel, 0.0)) for fuel in GENERATION_COLUMNS)

    if total_mw <= 1e-9:
        return CarbonMetrics(
            predicted_total_carbon_kgco2e=0.0,
            emissions_intensity_kgco2e_per_mwh=0.0,
            renewable_proportion=0.0,
        )

    # kg CO2-e per hour, at the current instantaneous mix.
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
