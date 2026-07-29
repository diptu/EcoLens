"""Tests for ecolens.ingestion.service.anomaly.baseline (root TODO.md's
"Anomaly Detection" section, v1 statistical layer).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ecolens.ingestion.core.settings import IngestionSettings
from ecolens.ingestion.service.anomaly.baseline import load_baseline


def _history_frame(n: int = 100, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "region": ["NSW1"] * n,
            "demand_mw": rng.normal(loc=6000.0, scale=200.0, size=n),
            "price_mwh": rng.normal(loc=80.0, scale=10.0, size=n),
        }
    )


class TestRollingBaseline:
    def test_normal_value_has_small_zscore(self):
        settings = IngestionSettings(anomaly_baseline_min_samples=20)
        baseline = load_baseline(
            "aemo_nem", settings=settings, history=_history_frame()
        )
        result = baseline.score(("NSW1",), "demand_mw", 6000.0)
        assert result.zscore is not None
        assert abs(result.zscore) < 1.0

    def test_extreme_value_has_large_zscore(self):
        settings = IngestionSettings(anomaly_baseline_min_samples=20)
        baseline = load_baseline(
            "aemo_nem", settings=settings, history=_history_frame()
        )
        result = baseline.score(("NSW1",), "demand_mw", 50_000.0)
        assert result.zscore is not None
        assert abs(result.zscore) > 10.0

    def test_unknown_entity_returns_none(self):
        settings = IngestionSettings(anomaly_baseline_min_samples=20)
        baseline = load_baseline(
            "aemo_nem", settings=settings, history=_history_frame()
        )
        result = baseline.score(("QLD1",), "demand_mw", 6000.0)
        assert result.zscore is None
        assert result.n_samples == 0

    def test_below_min_samples_returns_none(self):
        settings = IngestionSettings(anomaly_baseline_min_samples=1000)
        baseline = load_baseline(
            "aemo_nem", settings=settings, history=_history_frame(n=50)
        )
        result = baseline.score(("NSW1",), "demand_mw", 6000.0)
        assert result.zscore is None

    def test_empty_history_never_raises(self):
        settings = IngestionSettings()
        baseline = load_baseline("aemo_nem", settings=settings, history=pd.DataFrame())
        result = baseline.score(("NSW1",), "demand_mw", 6000.0)
        assert result.zscore is None

    def test_wem_has_no_entity_dimension(self):
        # WEM's unique key is (ts,) alone -- entity_columns_for_source
        # returns () -- baseline groups the whole history as one series.
        settings = IngestionSettings(anomaly_baseline_min_samples=20)
        history = pd.DataFrame(
            {"demand_mw": np.random.default_rng(1).normal(2000.0, 100.0, 100)}
        )
        baseline = load_baseline("aemo_wem", settings=settings, history=history)
        result = baseline.score((), "demand_mw", 2000.0)
        assert result.zscore is not None

    def test_degenerate_constant_series_does_not_divide_by_zero(self):
        settings = IngestionSettings(anomaly_baseline_min_samples=5)
        history = pd.DataFrame({"region": ["NSW1"] * 20, "demand_mw": [6000.0] * 20})
        baseline = load_baseline("aemo_nem", settings=settings, history=history)
        # any deviation from a perfectly constant history should score
        # as a large-but-finite z, not raise ZeroDivisionError/inf/nan.
        result = baseline.score(("NSW1",), "demand_mw", 6001.0)
        assert result.zscore is not None
        assert np.isfinite(result.zscore)

    def test_holidays_has_no_metrics_to_baseline(self):
        settings = IngestionSettings()
        baseline = load_baseline(
            "aemo_holidays", settings=settings, history=_history_frame()
        )
        result = baseline.score(("NSW1",), "demand_mw", 6000.0)
        assert result.zscore is None
