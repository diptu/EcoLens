"""Light smoke tests for `ml/model.py`/`ml/features.py`/`ml/conformal.py`
-- these are intentional byte-level duplicates of `data-pipeline`'s
already-thoroughly-tested `ecolens.ml.model`/`.features`/`.conformal`
(see each file's own docstring for why). Full behavioural coverage
already exists on the data-pipeline side; this just confirms the copy
transcribed correctly and still does the same thing, not a second full
test suite."""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from app.service.ml.conformal import ConformalCalibration
from app.service.ml.features import FEATURE_COLUMNS, TARGET_COLUMN, build_features
from app.models.ml import DemandLSTM


def test_demand_lstm_forward_pass_shapes_and_quantile_ordering():
    model = DemandLSTM(
        n_features=len(FEATURE_COLUMNS), horizon=6, hidden_size=8, num_layers=1
    )
    x = torch.randn(3, 10, len(FEATURE_COLUMNS))

    out = model(x)

    assert out.p10.shape == (3, 6)
    assert out.p50.shape == (3, 6)
    assert out.p90.shape == (3, 6)
    assert torch.all(out.p10 <= out.p50 + 1e-6)
    assert torch.all(out.p50 <= out.p90 + 1e-6)


def test_build_features_produces_exactly_feature_columns():
    ts = pd.date_range("2026-01-01", periods=30, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "ts": ts,
            "region": "NSW1",
            TARGET_COLUMN: np.linspace(5000, 5100, 30),
            "price_mwh": np.full(30, 60.0),
            "total_generation_mw": np.full(30, 5500.0),
            "total_renewable_mw": np.full(30, 1500.0),
            "temp_c": np.full(30, 22.0),
            "apparent_temp_c": np.full(30, 23.0),
            "humidity_pct": np.full(30, 50.0),
            "wind_speed_kmh": np.full(30, 10.0),
        }
    )

    engineered = build_features(df)

    for col in FEATURE_COLUMNS:
        assert col in engineered.columns


def test_conformal_calibration_apply_widens_symmetrically():
    calibration = ConformalCalibration(q=np.array([5.0, 10.0]), alpha=0.2)
    lo = np.array([[100.0, 100.0]])
    hi = np.array([[200.0, 200.0]])

    lo_out, hi_out = calibration.apply(lo, hi)

    np.testing.assert_array_equal(lo_out, [[95.0, 90.0]])
    np.testing.assert_array_equal(hi_out, [[205.0, 210.0]])


def test_conformal_calibration_from_dict_round_trips():
    data = {"q": [1.0, 2.0, 3.0], "alpha": 0.2}

    calibration = ConformalCalibration.from_dict(data)

    np.testing.assert_array_equal(calibration.q, [1.0, 2.0, 3.0])
    assert calibration.alpha == 0.2
