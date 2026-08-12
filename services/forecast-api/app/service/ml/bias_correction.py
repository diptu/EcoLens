"""Real per-region P50 bias correction (`TODO.md` Phase 3).

Real, measured problem this closes: even after `losses.py`'s Huber ->
pinball(0.5) fix for `demand_loss`'s point term (Phase 1/2, closes some
but not all of the gap), real per-region walk-forward bias
(`evaluate.py`'s `mean_error = mean(p50 - actual)`) still varies in both
sign and magnitude by region (measured as large as -343 MW) -- region is
already a one-hot input feature (`features.py::add_region_dummies`), but
a single shared point head evidently still can't fully null out
region-specific systematic offsets from that alone.

Why a per-region *constant offset*, not a learned regression model (the
`timesfm_correction.py` pattern -- Ridge on real residuals): that exact
approach already overfit once in this codebase (test MAPE 4.45% -> 6.96%
at 204 real training rows, before a `RidgeCV` per-target alpha search
fixed it) -- NEM regions have roughly 25-27 real calibration rows *per
region*, a worse-conditioned version of a problem that already failed at
higher volume. A constant is the right first lever; only escalate to
something richer (e.g. per-region-per-hour-bucket constants -- still no
regression) if real walk-forward residuals show a pattern a flat offset
can't capture (`TODO.md` Phase 3's own escalation criterion).

Fit once per region, at training time, on that region's own real
calibration split (`ml/train.py::train_model`'s existing per-region
loop already builds one, `region_cal_ds`, before conformal calibration
folds it into the pooled `cal_ds`) -- the same real, honest tradeoff
`conformal.py`'s own exchangeability caveat states plainly rather than
glossing over: bias is fit on the same cal rows conformal recalibrates
from (bias-then-conformal ordering, not a fully independent split --
there's no real data volume for a fourth disjoint one).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class DemandBiasCorrection:
    """`bias_by_region[region]`: shape `(horizon,)`, real `mean(actual -
    p50)` MW over that region's own calibration split -- positive means
    the model under-forecast on average for that region, negative means
    it over-forecast. A region absent from this dict (e.g. a model
    trained on a subset of regions) gets no correction, not an error.

    `.apply` shifts all three quantiles by the same real per-region
    amount, which trivially preserves `p10 <= p50 <= p90` (a uniform
    shift can't reorder them) -- applied at serving time right after
    `_inverse_target`, before `ConformalCalibration.apply` (see `TODO.md`
    Phase 3's own ordering note)."""

    bias_by_region: dict[str, np.ndarray] = field(default_factory=dict)

    def apply(
        self, region: str, p10: np.ndarray, p50: np.ndarray, p90: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        bias = self.bias_by_region.get(region)
        if bias is None:
            return p10, p50, p90
        return p10 + bias, p50 + bias, p90 + bias

    def to_dict(self) -> dict[str, list[float]]:
        return {region: arr.tolist() for region, arr in self.bias_by_region.items()}

    @classmethod
    def from_dict(cls, data: dict[str, list[float]]) -> DemandBiasCorrection:
        return cls(
            bias_by_region={
                region: np.array(vals, dtype=np.float64) for region, vals in data.items()
            }
        )
