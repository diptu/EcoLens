from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from app.service.ml.blend import BlendForecaster, _recent_mape, blend_forecasts


class TestBlendForecasts:
    def test_single_expert_gets_weight_one(self):
        predictions = {"a": (np.array([1.0]), np.array([2.0]), np.array([3.0]))}
        recent_mapes = {"a": 5.0}

        p10, p50, p90, weights = blend_forecasts(predictions, recent_mapes)

        assert weights == {"a": 1.0}
        assert np.array_equal(p10, [1.0])
        assert np.array_equal(p50, [2.0])
        assert np.array_equal(p90, [3.0])

    def test_lower_recent_mape_gets_higher_weight(self):
        predictions = {
            "good": (np.array([0.0]), np.array([100.0]), np.array([0.0])),
            "bad": (np.array([0.0]), np.array([200.0]), np.array([0.0])),
        }
        recent_mapes = {"good": 1.0, "bad": 10.0}

        _, _, _, weights = blend_forecasts(predictions, recent_mapes)

        assert weights["good"] > weights["bad"]

    def test_weights_sum_to_one(self):
        predictions = {
            "a": (np.zeros(3), np.zeros(3), np.zeros(3)),
            "b": (np.zeros(3), np.zeros(3), np.zeros(3)),
            "c": (np.zeros(3), np.zeros(3), np.zeros(3)),
        }
        recent_mapes = {"a": 5.0, "b": 8.0, "c": 3.0}

        _, _, _, weights = blend_forecasts(predictions, recent_mapes)

        assert sum(weights.values()) == pytest.approx(1.0)

    def test_p50_is_the_real_weighted_average(self):
        predictions = {
            "a": (np.array([0.0]), np.array([100.0]), np.array([0.0])),
            "b": (np.array([0.0]), np.array([200.0]), np.array([0.0])),
        }
        # Equal recent MAPE -> equal weight -> p50 should be the plain average.
        recent_mapes = {"a": 5.0, "b": 5.0}

        _, p50, _, weights = blend_forecasts(predictions, recent_mapes)

        assert weights["a"] == pytest.approx(weights["b"])
        assert p50[0] == pytest.approx(150.0)

    def test_raises_on_empty_predictions(self):
        with pytest.raises(ValueError):
            blend_forecasts({}, {})

    def test_raises_when_expert_names_dont_match(self):
        predictions = {"a": (np.zeros(1), np.zeros(1), np.zeros(1))}
        recent_mapes = {"b": 5.0}

        with pytest.raises(ValueError):
            blend_forecasts(predictions, recent_mapes)


def _history(n: int = 30) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC"),
            "region": "NSW1",
            "demand_mw": np.linspace(1000, 1000 + n, n),
        }
    )


@dataclass
class _ConstantForecaster:
    """A forecaster that always predicts a fixed p50 -- lets tests
    compute the *exact* real MAPE `_recent_mape` should find for known
    history, rather than needing a real trained model."""

    constant: float
    name: str = "constant"

    def predict(self, history, horizon):
        p50 = np.full(horizon, self.constant)
        return p50 - 10, p50, p50 + 10


class TestRecentMape:
    def test_computes_a_real_mape_against_known_history(self):
        history = _history(n=30)
        # Actual demand values are 1000..1029 (linspace); a constant
        # forecaster predicting exactly the mean of the recent window
        # should have some real, computable, nonzero MAPE, not 0 or inf.
        forecaster = _ConstantForecaster(constant=1015.0)

        mape = _recent_mape(forecaster, history, horizon=3, window=3)

        assert 0.0 < mape < float("inf")

    def test_perfect_forecaster_has_zero_recent_mape(self):
        history = _history(n=30)

        @dataclass
        class _PerfectForecaster:
            name: str = "perfect"

            def predict(self, history, horizon):
                # Cheats by reading the real answer straight out of
                # `history` -- exactly what `_recent_mape` is supposed to
                # score against, so this should come back ~0 error.
                actual = history["demand_mw"].to_numpy()
                # Not directly usable (predict doesn't see the future),
                # but for this synthetic linear series the next values
                # are perfectly predictable by extrapolation.
                step = actual[-1] - actual[-2]
                return (
                    np.full(horizon, actual[-1] + step) - 0.01,
                    np.array([actual[-1] + step * (i + 1) for i in range(horizon)]),
                    np.full(horizon, actual[-1] + step) + 0.01,
                )

            def __hash__(self):
                return id(self)

        mape = _recent_mape(_PerfectForecaster(), history, horizon=3, window=3)

        assert mape == pytest.approx(0.0, abs=1e-6)

    def test_returns_inf_when_history_too_short_to_score_any_origin(self):
        # horizon=3, window=3 -> smallest scorable origin is n-3-1; needs
        # n=3 for every k in 1..3 to land at origin<0 (unscorable).
        history = _history(n=3)
        forecaster = _ConstantForecaster(constant=1000.0)

        mape = _recent_mape(forecaster, history, horizon=3, window=3)

        assert mape == float("inf")


class TestBlendForecaster:
    def test_predict_returns_horizon_shaped_output(self):
        history = _history(n=30)
        blend = BlendForecaster(
            experts=[
                _ConstantForecaster(constant=1010.0, name="a"),
                _ConstantForecaster(constant=1020.0, name="b"),
            ],
            window=3,
        )

        p10, p50, p90 = blend.predict(history, horizon=3)

        assert p10.shape == p50.shape == p90.shape == (3,)
        assert not np.isnan(p50).any()

    def test_records_last_weights_summing_to_one(self):
        history = _history(n=30)
        blend = BlendForecaster(
            experts=[
                _ConstantForecaster(constant=1010.0, name="a"),
                _ConstantForecaster(constant=1020.0, name="b"),
            ],
            window=3,
        )

        blend.predict(history, horizon=3)

        assert set(blend.last_weights) == {"a", "b"}
        assert sum(blend.last_weights.values()) == pytest.approx(1.0)

    def test_gracefully_degrades_to_a_single_expert(self):
        history = _history(n=30)
        blend = BlendForecaster(
            experts=[_ConstantForecaster(constant=1010.0, name="only")], window=3
        )

        p10, p50, p90 = blend.predict(history, horizon=3)

        assert blend.last_weights == {"only": 1.0}
        assert np.allclose(p50, 1010.0)

    def test_returns_nan_when_every_expert_returns_nan(self):
        @dataclass
        class _NanForecaster:
            name: str = "nan"

            def predict(self, history, horizon):
                return (np.full(horizon, np.nan),) * 3

        history = _history(n=30)
        blend = BlendForecaster(experts=[_NanForecaster()], window=3)

        p10, p50, p90 = blend.predict(history, horizon=3)

        assert np.isnan(p50).all()
        assert blend.last_weights == {}

    def test_skips_a_nan_expert_but_still_blends_the_rest(self):
        @dataclass
        class _NanForecaster:
            name: str = "nan"

            def predict(self, history, horizon):
                return (np.full(horizon, np.nan),) * 3

        history = _history(n=30)
        blend = BlendForecaster(
            experts=[
                _NanForecaster(),
                _ConstantForecaster(constant=1010.0, name="ok"),
            ],
            window=3,
        )

        p10, p50, p90 = blend.predict(history, horizon=3)

        assert not np.isnan(p50).any()
        assert set(blend.last_weights) == {"ok"}
