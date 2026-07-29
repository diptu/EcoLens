"""Tests for ecolens.forecasting.model.fuel_ensemble (root TODO.md's
"Normalization Constraint Layer").
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ecolens.forecasting.model.fuel_ensemble import (
    FUEL_COLUMNS,
    FuelEnsemble,
    fit_fuel_ensemble,
)
from ecolens.forecasting.schema.features import FEATURE_COLUMNS


def _training_frame(n: int = 200, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(
        {col: rng.normal(size=n) for col in FEATURE_COLUMNS if col != "is_holiday"}
    )
    X["is_holiday"] = rng.integers(0, 2, size=n)
    # coal_black_mw is learnably related to demand_mw; the rest are pure
    # noise -- enough to prove fit_fuel_ensemble is actually fitting
    # per-column relationships, not just returning constants.
    y = pd.DataFrame(
        {fuel: rng.normal(loc=100, scale=5, size=n) for fuel in FUEL_COLUMNS}
    )
    y["coal_black_mw"] = 500 + 50 * X["demand_mw"] + rng.normal(scale=1, size=n)
    return X, y


class TestFitFuelEnsemble:
    def test_returns_a_model_per_fuel_column(self):
        X, y = _training_frame()
        ensemble = fit_fuel_ensemble(
            X, y, num_leaves=7, n_estimators=20, learning_rate=0.1, max_depth=-1
        )
        assert set(ensemble.models) == set(FUEL_COLUMNS)

    def test_raises_when_a_target_column_is_missing(self):
        X, y = _training_frame()
        y = y.drop(columns=["hydro_mw"])
        with pytest.raises(ValueError, match="hydro_mw"):
            fit_fuel_ensemble(
                X, y, num_leaves=7, n_estimators=20, learning_rate=0.1, max_depth=-1
            )

    def test_learns_a_real_relationship_not_just_noise(self):
        X, y = _training_frame(n=400)
        ensemble = fit_fuel_ensemble(
            X, y, num_leaves=15, n_estimators=100, learning_rate=0.1, max_depth=-1
        )
        preds = ensemble.predict(X)
        # coal_black_mw was constructed as a real (noisy-linear) function
        # of demand_mw -- a fitted model should track it far better than
        # the pure-noise fuel columns.
        coal_r2 = np.corrcoef(preds["coal_black_mw"], y["coal_black_mw"])[0, 1] ** 2
        noise_r2 = np.corrcoef(preds["wind_mw"], y["wind_mw"])[0, 1] ** 2
        assert coal_r2 > 0.8
        assert coal_r2 > noise_r2


class TestFuelEnsemble:
    def test_post_init_rejects_a_partial_model_dict(self):
        X, y = _training_frame()
        ensemble = fit_fuel_ensemble(
            X, y, num_leaves=7, n_estimators=20, learning_rate=0.1, max_depth=-1
        )
        partial = dict(ensemble.models)
        del partial["wind_mw"]
        with pytest.raises(ValueError, match="wind_mw"):
            FuelEnsemble(models=partial)

    def test_predict_row_matches_predict_dataframe(self):
        X, y = _training_frame()
        ensemble = fit_fuel_ensemble(
            X, y, num_leaves=7, n_estimators=20, learning_rate=0.1, max_depth=-1
        )
        row = X.iloc[[0]]
        via_predict = {fuel: float(v[0]) for fuel, v in ensemble.predict(row).items()}
        via_predict_row = ensemble.predict_row(row.iloc[0].to_dict())
        for fuel in FUEL_COLUMNS:
            assert via_predict[fuel] == pytest.approx(via_predict_row[fuel])
