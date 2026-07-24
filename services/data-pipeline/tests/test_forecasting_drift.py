"""Tests for ecolens.forecasting.mlops.drift (ECO-116)."""

from __future__ import annotations

import numpy as np

from ecolens.config import Settings
from ecolens.forecasting.mlops.drift import (
    feature_drift,
    population_stability_index,
    residual_drift,
)


class TestPopulationStabilityIndex:
    def test_identical_distributions_score_near_zero(self):
        rng = np.random.default_rng(0)
        ref = rng.normal(0, 1, 2000)
        same = rng.normal(0, 1, 500)
        assert population_stability_index(ref, same) < 0.1

    def test_shifted_distribution_scores_high(self):
        rng = np.random.default_rng(1)
        ref = rng.normal(0, 1, 2000)
        shifted = rng.normal(4, 1, 500)
        assert population_stability_index(ref, shifted) > 0.5

    def test_empty_input_is_zero_not_an_error(self):
        assert population_stability_index(np.array([]), np.array([1.0, 2.0])) == 0.0
        assert population_stability_index(np.array([1.0, 2.0]), np.array([])) == 0.0

    def test_constant_feature_is_zero_not_nan(self):
        ref = np.ones(100)
        current = np.ones(50)
        assert population_stability_index(ref, current) == 0.0


class TestFeatureDrift:
    def test_flags_only_the_drifted_feature(self):
        rng = np.random.default_rng(2)
        ref = {"temp_c": rng.normal(0, 1, 1000), "stable": rng.normal(0, 1, 1000)}
        current = {"temp_c": rng.normal(4, 1, 300), "stable": rng.normal(0, 1, 300)}
        settings = Settings(drift_psi_threshold=0.2)  # type: ignore[call-arg]

        report = feature_drift(ref, current, settings=settings)
        assert "temp_c" in report.drifting_features
        assert "stable" not in report.drifting_features
        assert report.is_drifting is True

    def test_no_drift_when_nothing_shifted(self):
        rng = np.random.default_rng(3)
        ref = {"a": rng.normal(0, 1, 1000)}
        current = {"a": rng.normal(0, 1, 300)}
        settings = Settings(drift_psi_threshold=0.2)  # type: ignore[call-arg]
        report = feature_drift(ref, current, settings=settings)
        assert report.is_drifting is False


class TestResidualDrift:
    def test_same_distribution_is_not_drifting(self):
        rng = np.random.default_rng(4)
        ref = rng.normal(0, 10, 500)
        current = rng.normal(0, 10, 200)
        settings = Settings(drift_residual_ks_alpha=0.01)  # type: ignore[call-arg]
        report = residual_drift(ref, current, settings=settings)
        assert report.is_drifting is False

    def test_shifted_residuals_are_drifting(self):
        rng = np.random.default_rng(5)
        ref = rng.normal(0, 10, 500)
        current = rng.normal(50, 10, 200)  # residuals got much bigger/biased
        settings = Settings(drift_residual_ks_alpha=0.01)  # type: ignore[call-arg]
        report = residual_drift(ref, current, settings=settings)
        assert report.is_drifting is True
