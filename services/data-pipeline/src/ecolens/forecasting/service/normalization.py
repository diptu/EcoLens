"""Root TODO.md's "Normalization Constraint Layer": "16 fuel types come
out of the per-fuel LightGBM ensemble independently; rescale them so they
sum back to total_demand_mw.p50 instead of trusting each fuel model's raw
output in isolation." This module is that rescale step -- a small, pure
function, deliberately kept separate from `model/fuel_ensemble.py` (the
thing being rescaled) and `forecast-api`'s serving path (the thing that
calls this per request), so the rescaling math itself is unit-testable
without a trained model or a live request in the loop.

Which of the 16 `fuel_ensemble.FUEL_COLUMNS` actually belong in a
"generation that serves demand" total is a real modeling decision, not
just an implementation detail:

  * `battery_charge_mw` is a *load* (energy going into storage), not
    generation -- including it in a sum that's supposed to equal demand
    would double-count that energy (once when whatever generated it is
    summed, again -- with the wrong sign semantics -- here).
  * `curtailment_solar_utility_mw`/`curtailment_wind_mw` are *foregone*
    generation (potential output that was intentionally not delivered to
    the grid) -- by definition not part of what actually served demand.

`GENERATION_COLUMNS` (the 13 fuel types actually summed/rescaled here) is
`fuel_ensemble.FUEL_COLUMNS` minus exactly those three -- the ensemble
still predicts all 16 independently (it's a generic per-column regressor,
see that module's own docstring), but only the true-generation subset
participates in the demand-matching rescale.
"""

from __future__ import annotations

from ecolens.forecasting.model.fuel_ensemble import FUEL_COLUMNS

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
    """Rescales `raw_predictions` (keyed by `GENERATION_COLUMNS`, or any
    subset/superset of it -- only `GENERATION_COLUMNS` keys present are
    touched, anything else passes through unscaled at 0.0, since it was
    never part of the total being matched) so the `GENERATION_COLUMNS`
    entries sum exactly to `target_total`.

    Negative raw predictions are clipped to 0 first -- a per-fuel
    LightGBM regressor has no non-negativity constraint built in and can
    legitimately predict a small negative value for a fuel that's
    usually near-zero (e.g. distillate/biomass off-peak); proportional
    rescaling against a positive target is only well-defined for
    non-negative components, and a negative predicted generation has no
    physical meaning to preserve anyway.

    If every (clipped) component is ~0 but `target_total` isn't, there's
    no informative proportion to preserve -- falls back to an equal
    split across `GENERATION_COLUMNS` rather than leaving the total
    unmatched (a caller that asked for "these fuels sum to
    `target_total`" gets exactly that back either way).
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

    # Non-generation keys (battery_charge_mw, curtailment_*) pass through
    # untouched at 0.0 in the rescaled view -- they were never part of
    # the total being matched (see module docstring), but a caller that
    # asked about one of them should still get a defined answer, not a
    # KeyError.
    for fuel in raw_predictions:
        if fuel not in rescaled:
            rescaled[fuel] = 0.0
    return rescaled


__all__ = ["GENERATION_COLUMNS", "rescale_to_total"]
