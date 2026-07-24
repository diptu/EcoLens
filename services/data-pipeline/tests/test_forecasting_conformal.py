"""Tests for ecolens.forecasting.evaluation.conformal (ECO-114)."""

from __future__ import annotations

import numpy as np
import pytest

from ecolens.forecasting.evaluation.conformal import (
    empirical_coverage,
    fit_conformal_calibration,
)


def _synthetic_quantiles(
    n: int, horizon: int, seed: int, *, band_half_width: float = 1.0
):
    """y_true ~ N(0,1); p10/p90 are a symmetric, possibly-too-narrow band
    around the true mean -- lets tests dial in exactly how miscalibrated
    the raw model is before calibration.
    """
    rng = np.random.default_rng(seed)
    y_true = rng.normal(0, 1, size=(n, horizon))
    p10 = np.full((n, horizon), -band_half_width)
    p90 = np.full((n, horizon), band_half_width)
    return p10, p90, y_true


class TestFitConformalCalibration:
    def test_calibrated_interval_achieves_target_coverage_on_held_out_data(self):
        # Calibrate on one sample, check coverage on an *independent* one
        # (the real CQR guarantee is about held-out data, not the
        # calibration set it was fit on).
        p10_cal, p90_cal, y_cal = _synthetic_quantiles(
            2000, 1, seed=0, band_half_width=0.3
        )
        calibration = fit_conformal_calibration(p10_cal, p90_cal, y_cal, alpha=0.2)

        p10_test, p90_test, y_test = _synthetic_quantiles(
            5000, 1, seed=1, band_half_width=0.3
        )
        p10_final, p90_final = calibration.calibrate(p10_test, p90_test)
        coverage = empirical_coverage(p10_final, p90_final, y_test)

        assert (
            coverage >= 0.8 - 0.03
        )  # 1 - alpha, with a little slack for sampling noise

    def test_wider_raw_band_needs_less_correction(self):
        narrow_p10, narrow_p90, y = _synthetic_quantiles(
            2000, 1, seed=2, band_half_width=0.2
        )
        wide_p10, wide_p90, _ = _synthetic_quantiles(
            2000, 1, seed=2, band_half_width=2.0
        )

        narrow_cal = fit_conformal_calibration(narrow_p10, narrow_p90, y, alpha=0.2)
        wide_cal = fit_conformal_calibration(wide_p10, wide_p90, y, alpha=0.2)

        assert narrow_cal.q_hat[0] > wide_cal.q_hat[0]

    def test_per_horizon_step_independent(self):
        rng = np.random.default_rng(3)
        n, horizon = 500, 3
        y_true = rng.normal(0, 1, size=(n, horizon))
        # Step 0 needs a big correction, step 2 needs almost none.
        p10 = np.stack([np.full(n, -0.1), np.full(n, -0.1), np.full(n, -5.0)], axis=1)
        p90 = np.stack([np.full(n, 0.1), np.full(n, 0.1), np.full(n, 5.0)], axis=1)
        calibration = fit_conformal_calibration(p10, p90, y_true, alpha=0.2)
        assert calibration.q_hat[0] > calibration.q_hat[2]

    def test_invalid_alpha_raises(self):
        p10, p90, y = _synthetic_quantiles(100, 1, seed=4)
        with pytest.raises(ValueError, match="alpha must be"):
            fit_conformal_calibration(p10, p90, y, alpha=1.5)

    def test_too_few_calibration_samples_raises(self):
        p10, p90, y = _synthetic_quantiles(5, 1, seed=5)
        with pytest.raises(ValueError, match="calibration split has only"):
            fit_conformal_calibration(p10, p90, y, alpha=0.2)

    def test_round_trip_dict(self):
        p10, p90, y = _synthetic_quantiles(200, 4, seed=6)
        calibration = fit_conformal_calibration(p10, p90, y, alpha=0.1)
        from ecolens.forecasting.evaluation.conformal import ConformalCalibration

        restored = ConformalCalibration.from_dict(calibration.to_dict())
        assert np.allclose(restored.q_hat, calibration.q_hat)
        assert restored.alpha == calibration.alpha


class TestEmpiricalCoverage:
    def test_full_coverage(self):
        y = np.array([[0.0, 0.0]])
        p10 = np.array([[-1.0, -1.0]])
        p90 = np.array([[1.0, 1.0]])
        assert empirical_coverage(p10, p90, y) == 1.0

    def test_zero_coverage(self):
        y = np.array([[5.0, 5.0]])
        p10 = np.array([[-1.0, -1.0]])
        p90 = np.array([[1.0, 1.0]])
        assert empirical_coverage(p10, p90, y) == 0.0
