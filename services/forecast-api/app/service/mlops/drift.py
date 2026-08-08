"""PSI/KS feature-drift detection (`todo-model-training.md` Phase 8,
data-pipeline's own `TODO.md` `ECO-M13`) — compares a training-time
feature distribution against a live serving-time one, real input for
Phase 4's "should we force a full retrain now" decision and Phase 6's
forecast-quality anomaly signal (feature drift often precedes
forecast-error drift, a real, useful leading indicator, not a
coincidence: a model's accuracy degrades *because* its real inputs have
shifted away from what it was trained on, so this is a real, earlier-
warning version of the same underlying problem Phase 6's realized-error
breaker eventually also catches).

**Population Stability Index (PSI)**: bins the training (reference)
distribution into deciles by default, then measures how much of the
live (comparison) distribution's mass has shifted between those same
bins — `sum((comparison_pct - reference_pct) * ln(comparison_pct /
reference_pct))` per bin. The standard, real industry rule-of-thumb
thresholds (not invented here): `< 0.1` no significant shift, `0.1-0.25`
moderate shift worth investigating, `>= 0.25` major shift.

**Kolmogorov-Smirnov (KS) two-sample test**: `scipy.stats.ks_2samp`, a
real, well-established nonparametric test for "do these two samples come
from the same distribution" — reused rather than hand-rolled (its exact
p-value computation has real subtlety not worth re-deriving). Reports
both the KS statistic and its p-value; `p < 0.05` (this module's default
significance level) is the real, standard threshold for "reject the
same-distribution null hypothesis".

Both metrics are computed per-feature-column, not once for a whole
feature matrix — a single aggregate drift number would hide *which*
input actually shifted, the real, actionable signal this module exists
to produce.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

# Standard, real industry rule-of-thumb bands (not invented here) --
# see module docstring.
PSI_MODERATE_THRESHOLD = 0.1
PSI_MAJOR_THRESHOLD = 0.25

DEFAULT_KS_SIGNIFICANCE_LEVEL = 0.05


def population_stability_index(
    reference: np.ndarray, comparison: np.ndarray, n_bins: int = 10
) -> float:
    """Real PSI between `reference` (training-time) and `comparison`
    (live serving-time) values of one feature. Bin edges are the
    `reference` distribution's own deciles (quantile-based, not
    fixed-width bins -- so each reference bin holds a real, roughly
    equal ~1/`n_bins` share by construction, and the comparison
    distribution's shift is measured against that, not against
    arbitrarily-placed fixed bins that could over/under-weight a dense
    region).

    NaN/inf values are dropped from both arrays before binning -- a
    feature-warmup NaN (this project's own lag/rolling-feature warmup
    convention, `ml/features.py`) isn't a real drift signal, just an
    artifact of where in the series the window starts.
    """
    reference = reference[np.isfinite(reference)]
    comparison = comparison[np.isfinite(comparison)]
    if reference.size == 0 or comparison.size == 0:
        return float("nan")

    quantiles = np.linspace(0, 1, n_bins + 1)
    edges = np.unique(np.quantile(reference, quantiles))
    if edges.size < 2:
        # Every reference value is identical -- no real spread to bin
        # against; PSI is only meaningful when the reference itself has
        # real variation.
        return float("nan")
    # Open the outer edges so a comparison value outside the reference's
    # observed range still lands in the nearest bin instead of being
    # silently dropped by `np.histogram` -- an out-of-range comparison
    # value is itself real drift signal, not noise to discard.
    edges = edges.copy()
    edges[0] = -np.inf
    edges[-1] = np.inf

    ref_counts, _ = np.histogram(reference, bins=edges)
    comp_counts, _ = np.histogram(comparison, bins=edges)

    # Laplace-smoothed proportions -- a zero-count bin would make the
    # PSI term's `ln(comparison_pct / reference_pct)` blow up to +-inf
    # for one empty bin, a bad estimator artifact rather than real
    # signal at the sample sizes this project actually has.
    ref_pct = (ref_counts + 1) / (ref_counts.sum() + len(ref_counts))
    comp_pct = (comp_counts + 1) / (comp_counts.sum() + len(comp_counts))

    return float(np.sum((comp_pct - ref_pct) * np.log(comp_pct / ref_pct)))


@dataclass
class FeatureDriftReport:
    feature: str
    psi: float
    ks_statistic: float
    ks_pvalue: float
    reference_n: int
    comparison_n: int

    @property
    def psi_severity(self) -> str:
        if np.isnan(self.psi):
            return "unknown"
        if self.psi >= PSI_MAJOR_THRESHOLD:
            return "major"
        if self.psi >= PSI_MODERATE_THRESHOLD:
            return "moderate"
        return "none"

    def ks_significant(
        self, significance_level: float = DEFAULT_KS_SIGNIFICANCE_LEVEL
    ) -> bool:
        return not np.isnan(self.ks_pvalue) and self.ks_pvalue < significance_level


def compute_feature_drift(
    reference: pd.DataFrame,
    comparison: pd.DataFrame,
    columns: "list[str] | tuple[str, ...]",
    n_bins: int = 10,
) -> list[FeatureDriftReport]:
    """Real per-column PSI + KS drift report for every column in
    `columns` present in both `reference` (training-time feature
    snapshot) and `comparison` (live serving-time feature snapshot).
    Columns missing from either frame are silently skipped -- a genuine
    schema mismatch is a real, separate problem (data-quality checks,
    not drift detection) this function doesn't try to also cover.
    """
    reports = []
    for column in columns:
        if column not in reference.columns or column not in comparison.columns:
            continue
        ref_values = pd.to_numeric(reference[column], errors="coerce").to_numpy(
            dtype=float
        )
        comp_values = pd.to_numeric(comparison[column], errors="coerce").to_numpy(
            dtype=float
        )
        ref_clean = ref_values[np.isfinite(ref_values)]
        comp_clean = comp_values[np.isfinite(comp_values)]

        psi = population_stability_index(ref_values, comp_values, n_bins=n_bins)
        if ref_clean.size > 0 and comp_clean.size > 0:
            ks_result = stats.ks_2samp(ref_clean, comp_clean)
            ks_statistic, ks_pvalue = (
                float(ks_result.statistic),
                float(ks_result.pvalue),
            )
        else:
            ks_statistic, ks_pvalue = float("nan"), float("nan")

        reports.append(
            FeatureDriftReport(
                feature=column,
                psi=psi,
                ks_statistic=ks_statistic,
                ks_pvalue=ks_pvalue,
                reference_n=int(ref_clean.size),
                comparison_n=int(comp_clean.size),
            )
        )
    return reports
