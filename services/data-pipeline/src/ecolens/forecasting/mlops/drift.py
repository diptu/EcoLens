"""ECO-116 (drift detection): feature drift via Population Stability
Index (PSI) and residual drift via a two-sample Kolmogorov-Smirnov
test, both over `Settings.drift_lookback_days`.

Two different questions, two different tests:
  * PSI answers "has the *input* distribution shifted" (e.g. a weather
    station swap, a new region's data starting to flow in) --
    comparing a recent window's feature distribution against the
    distribution the model was actually trained on.
  * The KS test answers "has the *model's error* distribution shifted"
    (e.g. the model is systematically worse lately even though inputs
    look normal) -- comparing recent residuals against a reference
    (e.g. the test-split residuals at evaluation time).

Both report a boolean `is_drifting` against `Settings.drift_psi_threshold`
/ `drift_residual_ks_alpha` so a caller (the health snapshot, or a
future alerting hook) doesn't have to know which statistic means what.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from ecolens.config import Settings, get_settings


@dataclass(frozen=True)
class FeatureDriftReport:
    psi_by_feature: dict[str, float]
    threshold: float

    @property
    def drifting_features(self) -> tuple[str, ...]:
        return tuple(
            f for f, psi in self.psi_by_feature.items() if psi > self.threshold
        )

    @property
    def is_drifting(self) -> bool:
        return len(self.drifting_features) > 0


@dataclass(frozen=True)
class ResidualDriftReport:
    statistic: float
    p_value: float
    alpha: float

    @property
    def is_drifting(self) -> bool:
        # A *small* p-value means "these two samples are unlikely to come
        # from the same distribution" -- i.e. drift.
        return self.p_value < self.alpha


def population_stability_index(
    reference: np.ndarray, current: np.ndarray, *, buckets: int = 10
) -> float:
    """Standard PSI: bucket `reference` into `buckets` equal-frequency
    bins, then compare `current`'s share of each bin against
    `reference`'s. 0 = identical distributions; > ~0.25 is the usual
    "seriously drifted" rule of thumb, `Settings.drift_psi_threshold`
    (default 0.2) is a bit more conservative than that.
    """
    reference = reference[~np.isnan(reference)]
    current = current[~np.isnan(current)]
    if len(reference) == 0 or len(current) == 0:
        return 0.0

    quantile_edges = np.unique(np.quantile(reference, np.linspace(0, 1, buckets + 1)))
    if len(quantile_edges) < 3:
        # Degenerate (near-constant) feature -- PSI isn't meaningful, and
        # there's nothing to bucket into more than one bin anyway.
        return 0.0
    quantile_edges[0], quantile_edges[-1] = -np.inf, np.inf

    ref_counts, _ = np.histogram(reference, bins=quantile_edges)
    cur_counts, _ = np.histogram(current, bins=quantile_edges)

    ref_pct = np.clip(ref_counts / max(len(reference), 1), 1e-4, None)
    cur_pct = np.clip(cur_counts / max(len(current), 1), 1e-4, None)

    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def feature_drift(
    reference: dict[str, np.ndarray],
    current: dict[str, np.ndarray],
    *,
    settings: Settings | None = None,
) -> FeatureDriftReport:
    """`reference`/`current`: feature name -> 1-D array of values, e.g.
    the train split vs. the most recent `drift_lookback_days` window.
    """
    settings = settings or get_settings()
    shared = sorted(set(reference) & set(current))
    psi_by_feature = {
        col: population_stability_index(reference[col], current[col]) for col in shared
    }
    return FeatureDriftReport(
        psi_by_feature=psi_by_feature, threshold=settings.drift_psi_threshold
    )


def residual_drift(
    reference_residuals: np.ndarray,
    current_residuals: np.ndarray,
    *,
    settings: Settings | None = None,
) -> ResidualDriftReport:
    """Two-sample KS test between a reference residual distribution
    (e.g. from evaluate.py's test split at training time) and a recent
    window's residuals.
    """
    settings = settings or get_settings()
    result = stats.ks_2samp(reference_residuals, current_residuals)
    return ResidualDriftReport(
        statistic=float(result.statistic),
        p_value=float(result.pvalue),
        alpha=settings.drift_residual_ks_alpha,
    )


__all__ = [
    "FeatureDriftReport",
    "ResidualDriftReport",
    "population_stability_index",
    "feature_drift",
    "residual_drift",
]
