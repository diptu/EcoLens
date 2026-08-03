"""Conformal calibration application — the read-only half of
`data-pipeline`'s `app.service.ml.conformal` (intentionally duplicated, see
`models/ml.py`'s docstring). This service never *fits* a calibration
(that only happens during training); it only applies the `q`/`alpha`
`data-pipeline` already computed and logged as `conformal_calibration.json`
(`service/ml/registry.py`'s `ModelBundle.calibration`)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ConformalCalibration:
    q: np.ndarray
    alpha: float

    def apply(self, lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return lo - self.q, hi + self.q

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ConformalCalibration:
        return cls(q=np.array(data["q"], dtype=np.float64), alpha=float(data["alpha"]))  # type: ignore[arg-type]
