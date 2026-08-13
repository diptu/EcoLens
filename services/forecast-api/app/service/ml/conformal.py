"""Conformalized quantile regression (CQR) — post-hoc calibration of
`DemandLSTM`'s raw P10/P90 outputs into intervals with a real, finite-
sample marginal coverage guarantee (Romano, Patterson & Candès, 2019,
"Conformalized Quantile Regression").

Why this exists even though `DemandLSTM` already predicts P10/P90 heads
directly: a quantile-regression head's raw output has no coverage
guarantee — it's only as good as the training loss got it, and pinball
loss alone tends to under-cover (the true value falls outside the
predicted interval more often than the target rate). CQR fixes this with
one number per horizon step, computed once on a held-out calibration
split the model never trained on: how far the raw interval was wrong on
calibration data, then widen (or, occasionally, tighten) the interval by
exactly that much at inference time. This is what `README.md` means by
"Uncertainty: Conformal prediction over the calibration set" — it's a
correction layer on top of the quantile heads, not a separate mechanism
that replaces them.

**Caveat, stated honestly rather than glossed over:** CQR's coverage
guarantee formally requires the calibration and test data to be
exchangeable (i.i.d., or at least not adversarially ordered). Chronological
time-series data violates this in general (a demand regime shift between
the calibration window and deployment breaks the guarantee) — this is the
same simplifying assumption most applied conformal-prediction-for-
forecasting work makes, not a bug specific to this implementation. See
`ml/train.py` for how the calibration split is carved out of the data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_ALPHA = 0.2  # miscoverage target for a P10-P90 (80%) interval


@dataclass
class ConformalCalibration:
    """`q`: shape `(horizon,)` — the per-horizon-step widening computed by
    `fit_conformal`. Persisted alongside the model (MLflow artifact) so
    inference can reproduce calibrated intervals without re-running
    calibration."""

    q: np.ndarray
    alpha: float

    def apply(self, lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """`lo`/`hi`: shape `(..., horizon)`, the model's raw P10/P90.
        Returns the calibrated `(lo, hi)` pair, same shape."""
        return lo - self.q, hi + self.q

    def to_dict(self) -> dict[str, object]:
        return {"q": self.q.tolist(), "alpha": self.alpha}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ConformalCalibration:
        return cls(q=np.array(data["q"], dtype=np.float64), alpha=float(data["alpha"]))  # type: ignore[arg-type]


def fit_conformal(
    y_cal: np.ndarray,
    lo_cal: np.ndarray,
    hi_cal: np.ndarray,
    alpha: float = DEFAULT_ALPHA,
) -> ConformalCalibration:
    """`y_cal`/`lo_cal`/`hi_cal`: shape `(n_samples, horizon)` — the true
    target and the model's raw P10/P90 on a held-out calibration split
    (never trained on, and not the validation split early-stopping
    watches — reusing either would leak information into the coverage
    guarantee this is supposed to provide).
    """
    if not (y_cal.shape == lo_cal.shape == hi_cal.shape):
        raise ValueError(
            "y_cal/lo_cal/hi_cal must all share the same (n_samples, horizon) shape"
        )
    n = y_cal.shape[0]
    if n < 2:
        raise ValueError("need at least 2 calibration samples")

    # Nonconformity score per (Romano et al. 2019, eq. 3): how far y falls
    # outside [lo, hi] -- positive if outside (either side), negative
    # (i.e. "room to spare") if inside.
    scores = np.maximum(lo_cal - y_cal, y_cal - hi_cal)

    # The finite-sample-corrected quantile level (eq. 6) -- using the
    # plain (1-alpha) quantile of `n` samples would under-cover by a
    # sample-size-dependent amount; this ceiling correction is what makes
    # the guarantee exact (>= 1-alpha) for finite n, not just asymptotic.
    level = min(1.0, np.ceil((1 - alpha) * (n + 1)) / n)
    q = np.quantile(scores, level, axis=0, method="higher")
    return ConformalCalibration(q=np.asarray(q, dtype=np.float64), alpha=alpha)


def empirical_coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    """Fraction of `y` values that actually fall within `[lo, hi]` —
    logged to MLflow so a calibration's real coverage (vs. the `1-alpha`
    target) is visible per training run, not just assumed correct."""
    return float(np.mean((y >= lo) & (y <= hi)))
