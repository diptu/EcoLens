"""Turns the fuel ensemble's nowcast into a *forecast-horizon* source
breakdown -- root TODO.md's "API & Registry Serving" section, the
`source_breakdown_mw`/`carbon_metrics` blocks.

data-pipeline's `model/fuel_ensemble.py` is a nowcast regressor (predicts
each fuel's MW from *contemporaneous* covariates, no lookback window --
see that module's own docstring for why a second sequence model wasn't
built for this). There's no way to get *future* covariates for a horizon
step the way the LSTM/TFT/TimesFM get future demand from their own
lookback windows, so this module makes a deliberate, documented
simplification instead of pretending otherwise: predict the fuel mix
*shares* (proportions, not absolute MW) from the latest known feature row,
then hold those shares constant across every horizon step, scaling them by
that step's own predicted `p50` demand. This is "the current generation
mix, applied to how big the grid is expected to be at each future
half-hour" -- a reasonable planning-level approximation, not a claim that
the *mix itself* is independently forecast per step.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .carbon import CarbonMetrics, compute_carbon_metrics
from .features import FEATURE_COLUMNS
from .fuel_loader import LoadedFuelEnsemble
from .normalization import rescale_to_total


def _predict_shares(
    loaded: LoadedFuelEnsemble, feature_row: dict[str, Any]
) -> dict[str, float]:
    """Nowcasts the nearest source mix from `feature_row`'s contemporaneous
    covariates, then rescales to `target_total=1.0` -- turning the raw
    per-fuel MW predictions into *proportions* that sum to 1, independent
    of whatever the nowcast's own (likely off) absolute magnitude was.
    """
    row_df = pd.DataFrame([{col: float(feature_row[col]) for col in FEATURE_COLUMNS}])
    # `PyFuncModel.predict`'s return type is a broad union (mlflow's own
    # PyFuncOutput) since a pyfunc model could in principle return
    # anything -- this one always returns the DataFrame
    # `_FuelEnsemblePyfuncModel.predict` builds (train_fuel_ensemble.py),
    # so narrow it back down explicitly rather than losing that guarantee
    # to `Any` (or an `assert`, which optimized bytecode can strip).
    predictions = loaded.model.predict(row_df)
    if not isinstance(predictions, pd.DataFrame):
        raise TypeError(
            f"fuel ensemble model {loaded.version!r} returned "
            f"{type(predictions).__name__}, expected a DataFrame -- has the "
            "pyfunc contract in data-pipeline's train_fuel_ensemble.py changed?"
        )
    raw = predictions.iloc[0].to_dict()
    return rescale_to_total(raw, target_total=1.0)


def forecast_source_breakdown(
    loaded: LoadedFuelEnsemble,
    feature_row: dict[str, Any],
    *,
    step_p50_values: list[float | None],
    interval_minutes: int,
) -> list[tuple[dict[str, float] | None, CarbonMetrics | None]]:
    """One `(source_breakdown_mw, carbon_metrics)` pair per entry in
    `step_p50_values`, in order -- `routes.py` zips this back onto its own
    `steps` list. A `None` p50 (shouldn't normally happen -- both
    forecasters always populate it -- but the response schema allows it)
    produces `(None, None)` for that step rather than a fabricated 0.
    """
    shares = _predict_shares(loaded, feature_row)
    interval_hours = interval_minutes / 60.0

    results: list[tuple[dict[str, float] | None, CarbonMetrics | None]] = []
    for p50 in step_p50_values:
        if p50 is None:
            results.append((None, None))
            continue
        breakdown = {fuel: share * p50 for fuel, share in shares.items()}
        carbon = compute_carbon_metrics(breakdown, interval_hours=interval_hours)
        results.append((breakdown, carbon))
    return results


__all__ = ["forecast_source_breakdown"]
