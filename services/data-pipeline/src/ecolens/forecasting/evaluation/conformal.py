"""ECO-114 (conformal calibration): Conformalized Quantile Regression
(CQR -- Romano, Patterson & Candes, 2019) turns the LSTM's raw P10/P90
heads into intervals with a distribution-free marginal coverage
guarantee, using `Settings.conformal_alpha` and a calibration split
(`WindowedDataset.calibration`) the model never trained or
early-stopped on -- reusing train or val data here would just recover
the model's already-known-optimistic self-assessment, not a real
guarantee.

One correction is fit per horizon step, since a 30-minute-ahead
forecast and a 24-hour-ahead one have very different, and separately
mis-calibrated, uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ConformalCalibration:
    """Per-horizon-step additive correction: calibrated interval is
    `[p10_raw - q_hat, p90_raw + q_hat]`. Widens an overconfident raw
    band, narrows an overcautious one -- whichever the calibration
    split says is actually needed for `1 - alpha` coverage.
    """

    q_hat: np.ndarray  # (horizon,), MW scale
    alpha: float

    def calibrate(
        self, p10_raw: np.ndarray, p90_raw: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """`p10_raw`/`p90_raw`: `(n, horizon)`, MW scale -> calibrated `(p10, p90)`."""
        return p10_raw - self.q_hat, p90_raw + self.q_hat

    def to_dict(self) -> dict[str, list[float] | float]:
        return {"q_hat": self.q_hat.tolist(), "alpha": self.alpha}

    @classmethod
    def from_dict(cls, d: dict) -> "ConformalCalibration":
        return cls(q_hat=np.asarray(d["q_hat"], dtype=np.float64), alpha=d["alpha"])


def fit_conformal_calibration(
    p10_raw: np.ndarray,
    p90_raw: np.ndarray,
    y_true: np.ndarray,
    *,
    alpha: float,
) -> ConformalCalibration:
    """All arrays `(n_calibration, horizon)`, MW scale.

    The CQR nonconformity score is how far outside `[p10, p90]` the
    true value actually fell (negative if it was already inside); the
    `ceil((n+1)(1-alpha))/n` finite-sample-corrected quantile of that
    score is the additive slack needed so the *calibrated* interval
    covers at least `1 - alpha` of held-out points, not just the
    calibration set itself.
    """
    if not (0 < alpha < 1):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    scores = np.maximum(p10_raw - y_true, y_true - p90_raw)
    n = scores.shape[0]
    if n < 10:
        raise ValueError(
            f"calibration split has only {n} samples -- CQR's finite-sample "
            "guarantee needs a meaningfully sized held-out set, not a handful "
            "of points"
        )
    q_level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
    q_hat = np.quantile(scores, q_level, axis=0, method="higher")
    return ConformalCalibration(q_hat=q_hat, alpha=alpha)


def empirical_coverage(p10: np.ndarray, p90: np.ndarray, y_true: np.ndarray) -> float:
    """Fraction of `y_true` that actually fell within `[p10, p90]` --
    should be >= `1 - alpha` on held-out (e.g. test-split) data if
    calibration is working as intended.
    """
    covered = (y_true >= p10) & (y_true <= p90)
    return float(covered.mean())


__all__ = [
    "ConformalCalibration",
    "fit_conformal_calibration",
    "empirical_coverage",
]
