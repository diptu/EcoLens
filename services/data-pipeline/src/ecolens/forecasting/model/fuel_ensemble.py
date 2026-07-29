"""Root TODO.md's "Normalization Constraint Layer": "16 fuel types come
out of the per-fuel LightGBM ensemble independently." No such ensemble
existed anywhere in this repo before this module -- `fact_generation_30min`
(warehouse mart) already carries the 16 per-fuel MW columns this trains
against, but nothing predicted them. This is that ensemble: one
independent `LGBMRegressor` per fuel type, each predicting that fuel's
generation MW from the same contemporaneous covariates
(`schema.features.FEATURE_COLUMNS`) the demand models train on.

Deliberately a *nowcast* regressor, not a sequence model like the LSTM/TFT/
TimesFM above -- LightGBM has no notion of a lookback window, and a second
16-headed sequence model would be a much larger, structurally different
undertaking than "give the existing per-fuel mart columns a predictive
model." `service/fuel_forecast.py` (forecast-api side) is what turns this
nowcast into a *forecast-horizon* source breakdown: predict the fuel-mix
*shares* from the latest known covariates, then apply those shares to each
horizon step's predicted `total_demand_mw.p50` (see that module's
docstring for the full reasoning) -- a documented simplification, not an
attempt to forecast 16 independent future fuel trajectories with a tabular
model.

Not a `torch.nn.Module` -- structurally unlike `DemandLSTM`/`DemandTFT` on
purpose, so `mlops/registry.py`'s `ForecastingModel` protocol (state_dict
+ architecture_dict) doesn't apply here; `training/train_fuel_ensemble.py`
persists this ensemble as one `mlflow.pyfunc` model instead of forcing it
through that torch-shaped contract (see that module's own docstring).

`OMP_NUM_THREADS=1` set below, before `lightgbm` is imported: a *second*,
worse variant of the SIGSEGV `feature_selection.py`'s Step 4 already
documents (`n_jobs=1` at the `LGBMRegressor` call site there is enough to
stop *that* crash). This module's own `n_jobs`/`num_threads=1` args on
every `fit`/`predict` call reduce but don't eliminate a real, reproducible
crash observed on this machine when LightGBM inference (`.predict()`, not
just `.fit()`) runs in the same process as actual torch computation
(not just a bare `import torch`) -- e.g. this repo's own test suite
running `test_forecasting_cli.py`'s real `DemandLSTM` training alongside
these fuel-ensemble tests. Once LightGBM's native OpenMP runtime has
initialized its thread pool (at first `.fit()`/`.predict()` call), a later
per-call `n_jobs=1`/`num_threads=1` only limits how many of those threads
a given call *uses* -- it doesn't shrink or re-init the pool itself, which
can still race with torch's own native thread pool during interpreter
shutdown/thread-join. Forcing the env var before LightGBM's C extension
ever loads makes the pool exactly 1 thread from the start, not just
1-thread-per-call on top of a wider pool.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Must happen before `from lightgbm import ...` below -- see module
# docstring. setdefault, not a hard set: an operator who's deliberately
# tuned OMP_NUM_THREADS for their own environment should still win.
os.environ.setdefault("OMP_NUM_THREADS", "1")

from lightgbm import LGBMRegressor  # noqa: E402 - must follow the OMP_NUM_THREADS setdefault above

from ecolens.forecasting.schema.features import FEATURE_COLUMNS

# The 16 fuel-type MW columns `fact_generation_30min.sql` carries --
# battery_charge_mw (a load, not generation) and the two curtailment_*
# columns (foregone-not-delivered energy) are included here because the
# mart reports them alongside the other 14 true generation columns and the
# ensemble treats "predict every column independently" uniformly; whether
# a given fuel's *raw* prediction should count toward the
# demand-serving total is `service/normalization.py`'s concern (it
# excludes exactly those three), not this module's.
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


@dataclass(frozen=True)
class FuelEnsemble:
    """One independently-fit `LGBMRegressor` per `FUEL_COLUMNS` entry.
    `models` must have exactly `FUEL_COLUMNS`' keys -- enforced in
    `__post_init__` so a caller can't silently predict against a partial
    ensemble (e.g. after a training run that failed for one fuel type).
    """

    models: dict[str, LGBMRegressor]

    def __post_init__(self) -> None:
        missing = [f for f in FUEL_COLUMNS if f not in self.models]
        if missing:
            raise ValueError(f"FuelEnsemble is missing models for: {missing}")

    def predict(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """`X` must carry every `FEATURE_COLUMNS` column, in any order
        (selected by name below, not position). Returns one `(n,)` array
        of raw, independently-predicted MW per fuel type -- not yet
        rescaled to sum to anything (see `service/normalization.py`).

        `num_threads=1`: same real SIGSEGV `fit_fuel_ensemble`'s own
        `n_jobs=1` guards against (LightGBM's multi-threaded pool crashing
        in a process that already imported torch), reproduced here too --
        `LGBMRegressor.predict()`'s own thread count isn't reliably
        inherited from the constructor's `n_jobs` in every LightGBM
        version, so it's pinned explicitly at call time as well, not just
        assumed to follow from the `fit_fuel_ensemble`-time setting.
        """
        x = X[list(FEATURE_COLUMNS)]
        return {
            fuel: np.asarray(self.models[fuel].predict(x, num_threads=1))
            for fuel in FUEL_COLUMNS
        }

    def predict_row(self, features: dict[str, float]) -> dict[str, float]:
        """Single-row convenience wrapper over `predict` -- what
        forecast-api's `fuel_forecast.py` calls per request (one feature
        row in, one `{fuel: mw}` dict out), rather than every caller
        building a one-row DataFrame by hand.
        """
        row = pd.DataFrame([features])
        raw = self.predict(row)
        return {fuel: float(values[0]) for fuel, values in raw.items()}


def fit_fuel_ensemble(
    X: pd.DataFrame,
    y: pd.DataFrame,
    *,
    num_leaves: int,
    n_estimators: int,
    learning_rate: float,
    max_depth: int,
) -> FuelEnsemble:
    """Fits one `LGBMRegressor` per `FUEL_COLUMNS` entry against the same
    `X` (`FEATURE_COLUMNS`-shaped covariates). `y` must carry every
    `FUEL_COLUMNS` column.

    `n_jobs=1`: same real, reproducible SIGSEGV `feature_selection.py`'s
    Step 4 already found and fixed the same way -- LightGBM's default
    multi-threaded OpenMP pool crashes hard in any process that already
    imported `torch` (confirmed there directly; `n_jobs=1` is the one
    thing that reliably avoids it). This module lives alongside
    torch-importing siblings under `forecasting/`, so any process
    importing both (this repo's own test suite included) would hit it by
    default without this.
    """
    missing = [f for f in FUEL_COLUMNS if f not in y.columns]
    if missing:
        raise ValueError(f"y is missing target columns for: {missing}")

    x = X[list(FEATURE_COLUMNS)]
    models: dict[str, LGBMRegressor] = {}
    for fuel in FUEL_COLUMNS:
        model = LGBMRegressor(
            num_leaves=num_leaves,
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            max_depth=max_depth,
            n_jobs=1,
            verbose=-1,
        )
        model.fit(x, y[fuel])
        models[fuel] = model
    return FuelEnsemble(models=models)


__all__ = ["FUEL_COLUMNS", "FuelEnsemble", "fit_fuel_ensemble"]
