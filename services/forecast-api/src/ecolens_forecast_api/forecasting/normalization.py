"""Structural duplicates of data-pipeline's `model/fuel_ensemble.py`
(`FUEL_COLUMNS`) and `service/normalization.py` (`GENERATION_COLUMNS`,
`rescale_to_total`) -- same rationale `loader.py`/`features.py`'s own
docstrings already give for `DemandLSTM`/`FeatureScaler`: this service
loads the fuel ensemble as a generic `mlflow.pyfunc` model (see
`fuel_loader.py`), never as a data-pipeline `FuelEnsemble` instance, so it
never needs that package importable here -- but the *column names* and
*rescale math* still need to agree exactly, which is what's duplicated.
"""

from __future__ import annotations

FUEL_COLUMNS: tuple[str, ...] = (
    "coal_black_mw",
    "coal_brown_mw",
    "gas_ccgt_mw",
    "gas_ocgt_mw",
    "gas_other_mw",
    "hydro_mw",
    "pumped_hydro_mw",
    "wind_mw",
    "solar_utility_mw",
    "solar_rooftop_mw",
    "biomass_mw",
    "distillate_mw",
    "battery_discharge_mw",
    "battery_charge_mw",
    "curtailment_solar_utility_mw",
    "curtailment_wind_mw",
)

_EXCLUDED_FROM_GENERATION_TOTAL = (
    "battery_charge_mw",
    "curtailment_solar_utility_mw",
    "curtailment_wind_mw",
)

GENERATION_COLUMNS: tuple[str, ...] = tuple(
    f for f in FUEL_COLUMNS if f not in _EXCLUDED_FROM_GENERATION_TOTAL
)


def rescale_to_total(
    raw_predictions: dict[str, float], target_total: float
) -> dict[str, float]:
    """Identical math to data-pipeline's `service/normalization.py`'s
    `rescale_to_total` -- see that module's docstring for the full
    reasoning (why negatives are clipped, why battery_charge_mw/
    curtailment_* are excluded, the zero-total fallback).
    """
    clipped = {
        fuel: max(0.0, raw_predictions.get(fuel, 0.0)) for fuel in GENERATION_COLUMNS
    }
    total_raw = sum(clipped.values())

    if total_raw > 1e-9:
        scale = target_total / total_raw
        rescaled = {fuel: value * scale for fuel, value in clipped.items()}
    elif abs(target_total) <= 1e-9:
        rescaled = dict.fromkeys(GENERATION_COLUMNS, 0.0)
    else:
        share = target_total / len(GENERATION_COLUMNS)
        rescaled = dict.fromkeys(GENERATION_COLUMNS, share)

    for fuel in raw_predictions:
        if fuel not in rescaled:
            rescaled[fuel] = 0.0
    return rescaled


__all__ = ["FUEL_COLUMNS", "GENERATION_COLUMNS", "rescale_to_total"]
