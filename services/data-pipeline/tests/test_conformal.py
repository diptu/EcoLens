from __future__ import annotations

import numpy as np
import pytest

from app.service.ml.conformal import (
    ConformalCalibration,
    empirical_coverage,
    fit_conformal,
)


class TestFitConformal:
    def test_rejects_mismatched_shapes(self):
        y = np.zeros((10, 4))
        lo = np.zeros((10, 5))
        hi = np.zeros((10, 4))

        with pytest.raises(ValueError):
            fit_conformal(y, lo, hi)

    def test_rejects_fewer_than_2_samples(self):
        y = np.zeros((1, 4))

        with pytest.raises(ValueError):
            fit_conformal(y, y, y)

    def test_widening_is_zero_when_raw_interval_already_covers_everything(self):
        rng = np.random.default_rng(0)
        y = rng.normal(size=(500, 3))
        lo = np.full_like(y, -100.0)
        hi = np.full_like(y, 100.0)

        calibration = fit_conformal(y, lo, hi, alpha=0.2)

        assert np.all(
            calibration.q <= 0
        )  # scores are all negative -> no widening needed

    def test_calibrated_interval_achieves_target_coverage_on_held_out_data(self):
        """The actual point of CQR: an intentionally too-narrow raw
        interval, once calibrated on one i.i.d. sample and applied to a
        *different* i.i.d. sample from the same distribution, should hit
        (at least) the 1-alpha target coverage -- not just look plausible.
        """
        rng = np.random.default_rng(42)
        horizon = 6
        n = 3000
        alpha = 0.2

        def sample(n_samples: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
            y = rng.normal(loc=100.0, scale=10.0, size=(n_samples, horizon))
            # Deliberately too-narrow raw "model" quantiles (a fixed +-5
            # band around the true mean) -- on its own this would badly
            # under-cover a distribution with std=10.
            lo = np.full((n_samples, horizon), 95.0)
            hi = np.full((n_samples, horizon), 105.0)
            return y, lo, hi

        y_cal, lo_cal, hi_cal = sample(n)
        calibration = fit_conformal(y_cal, lo_cal, hi_cal, alpha=alpha)

        y_test, lo_test, hi_test = sample(n)
        lo_calibrated, hi_calibrated = calibration.apply(lo_test, hi_test)

        raw_coverage = empirical_coverage(y_test, lo_test, hi_test)
        calibrated_coverage = empirical_coverage(y_test, lo_calibrated, hi_calibrated)

        assert raw_coverage < 0.8  # confirms the raw interval really was too narrow
        assert (
            calibrated_coverage >= (1 - alpha) - 0.02
        )  # small slack for sampling noise


class TestConformalCalibrationDictRoundTrip:
    def test_to_dict_from_dict_round_trip(self):
        calibration = ConformalCalibration(q=np.array([1.0, 2.5, 3.0]), alpha=0.2)

        restored = ConformalCalibration.from_dict(calibration.to_dict())

        np.testing.assert_array_equal(restored.q, calibration.q)
        assert restored.alpha == calibration.alpha
