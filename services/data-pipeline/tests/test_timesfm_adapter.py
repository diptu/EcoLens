from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.models.timesfm_adapter import (
    TimesFMForecaster,
    load_timesfm_forecaster,
)


class _FakeTimesFMModel:
    """Stands in for a real, loaded+compiled `TimesFM_2p5_200M_torch` --
    `forecast()`'s real return shape is `(point_forecast, quantile_forecast)`
    with `quantile_forecast` shaped `(batch, horizon, 10)`: column 0 is the
    mean, columns 1-9 are deciles 0.1..0.9 (confirmed against the real
    model in `timesfm_adapter.py`'s module docstring)."""

    def __init__(self, horizon_seen: list[int] | None = None) -> None:
        self.horizon_seen = horizon_seen if horizon_seen is not None else []

    def forecast(self, horizon: int, inputs: list[np.ndarray]):
        self.horizon_seen.append(horizon)
        batch = len(inputs)
        point = np.full((batch, horizon), 100.0)
        quantiles = np.zeros((batch, horizon, 10))
        # deciles 0.1..0.9 at columns 1-9, spaced 10 units apart so p10/
        # p50/p90 are trivially distinguishable in assertions below.
        for i in range(1, 10):
            quantiles[:, :, i] = 100.0 + (i - 5) * 10.0
        quantiles[:, :, 0] = 100.0  # mean column, unused by the adapter
        return point, quantiles


def _history(n: int = 20, target_col: str = "demand_mw") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC"),
            "region": "WEM",
            target_col: np.linspace(1000, 1000 + n, n),
        }
    )


class TestTimesFMForecaster:
    def test_predict_returns_horizon_shaped_p10_p50_p90(self):
        model = _FakeTimesFMModel()
        forecaster = TimesFMForecaster(model=model, max_horizon=12)

        p10, p50, p90 = forecaster.predict(_history(), horizon=6)

        assert p10.shape == p50.shape == p90.shape == (6,)
        assert model.horizon_seen == [6]

    def test_p50_matches_the_decile_5_column_and_p10_lt_p50_lt_p90(self):
        model = _FakeTimesFMModel()
        forecaster = TimesFMForecaster(model=model, max_horizon=12)

        p10, p50, p90 = forecaster.predict(_history(), horizon=4)

        assert np.allclose(p50, 100.0)
        assert np.allclose(p10, 60.0)  # decile 0.1 -> column 1 -> (1-5)*10=-40
        assert np.allclose(p90, 140.0)  # decile 0.9 -> column 9 -> (9-5)*10=+40
        assert (p10 < p50).all()
        assert (p50 < p90).all()

    def test_raises_when_horizon_exceeds_max_horizon(self):
        model = _FakeTimesFMModel()
        forecaster = TimesFMForecaster(model=model, max_horizon=4)

        with pytest.raises(ValueError):
            forecaster.predict(_history(), horizon=6)

    def test_returns_nan_for_empty_history(self):
        model = _FakeTimesFMModel()
        forecaster = TimesFMForecaster(model=model, max_horizon=12)
        empty = _history(n=0)

        p10, p50, p90 = forecaster.predict(empty, horizon=4)

        assert np.isnan(p10).all()
        assert np.isnan(p50).all()
        assert np.isnan(p90).all()
        assert model.horizon_seen == []

    def test_drops_nan_rows_before_forecasting(self):
        model = _FakeTimesFMModel()
        forecaster = TimesFMForecaster(model=model, max_horizon=12)
        history = _history(n=10)
        history.loc[3, "demand_mw"] = np.nan

        p10, p50, p90 = forecaster.predict(history, horizon=3)

        assert not np.isnan(p50).any()


class TestLoadTimesFMForecaster:
    def test_loads_and_compiles_with_the_given_context_and_horizon(self, monkeypatch):
        import app.models.timesfm_adapter as adapter_module

        captured = {}

        class _FakeModule:
            @staticmethod
            def TimesFM_2p5_200M_torch_from_pretrained(repo_id, revision):
                captured["repo_id"] = repo_id
                captured["revision"] = revision
                return _FakeCompilable()

        class _FakeCompilable:
            def compile(self, config):
                captured["config"] = config

        class _FakeTimesFM_2p5_200M_torch:
            @classmethod
            def from_pretrained(cls, repo_id, revision=None):
                return _FakeModule.TimesFM_2p5_200M_torch_from_pretrained(
                    repo_id, revision
                )

        class _FakeForecastConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_timesfm = type(
            "fake_timesfm",
            (),
            {
                "TimesFM_2p5_200M_torch": _FakeTimesFM_2p5_200M_torch,
                "ForecastConfig": _FakeForecastConfig,
            },
        )

        monkeypatch.setitem(__import__("sys").modules, "timesfm", fake_timesfm)

        # max_horizon=8 -> rounded up to 128 (the real checkpoint's output
        # patch size) both in what's passed to `ForecastConfig` and in the
        # returned forecaster's own `max_horizon` -- see
        # `_round_up_to_output_patch`'s docstring.
        forecaster = load_timesfm_forecaster(max_context=100, max_horizon=8)

        assert captured["repo_id"] == adapter_module.TIMESFM_REPO_ID
        assert captured["revision"] == adapter_module.TIMESFM_REVISION
        assert captured["config"].kwargs["max_context"] == 100
        assert captured["config"].kwargs["max_horizon"] == 128
        assert forecaster.max_horizon == 128


class TestRoundUpToOutputPatch:
    def test_rounds_up_to_the_next_multiple_of_128(self):
        from app.models.timesfm_adapter import _round_up_to_output_patch

        assert _round_up_to_output_patch(1) == 128
        assert _round_up_to_output_patch(64) == 128
        assert _round_up_to_output_patch(128) == 128
        assert _round_up_to_output_patch(129) == 256
