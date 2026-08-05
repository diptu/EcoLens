from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.service.mlops.drift import (
    PSI_MAJOR_THRESHOLD,
    PSI_MODERATE_THRESHOLD,
    FeatureDriftReport,
    compute_feature_drift,
    population_stability_index,
)


class TestPopulationStabilityIndex:
    def test_identical_distributions_have_near_zero_psi(self):
        rng = np.random.default_rng(0)
        reference = rng.normal(loc=100, scale=10, size=2000)
        comparison = reference.copy()

        psi = population_stability_index(reference, comparison)

        assert psi == pytest.approx(0.0, abs=1e-6)

    def test_a_shifted_distribution_has_real_positive_psi(self):
        rng = np.random.default_rng(0)
        reference = rng.normal(loc=100, scale=10, size=2000)
        # A meaningfully shifted comparison -- shifted by 3 standard
        # deviations, should land in the "major" band.
        comparison = rng.normal(loc=130, scale=10, size=2000)

        psi = population_stability_index(reference, comparison)

        assert psi > PSI_MAJOR_THRESHOLD

    def test_a_slightly_shifted_distribution_has_a_smaller_psi_than_a_big_shift(self):
        rng = np.random.default_rng(0)
        reference = rng.normal(loc=100, scale=10, size=2000)
        small_shift = rng.normal(loc=102, scale=10, size=2000)
        big_shift = rng.normal(loc=140, scale=10, size=2000)

        psi_small = population_stability_index(reference, small_shift)
        psi_big = population_stability_index(reference, big_shift)

        assert psi_small < psi_big

    def test_drops_nan_and_inf_before_binning(self):
        rng = np.random.default_rng(0)
        reference = rng.normal(loc=100, scale=10, size=500)
        comparison = np.concatenate([reference.copy(), [np.nan, np.inf, -np.inf]])

        psi = population_stability_index(reference, comparison)

        assert psi == pytest.approx(0.0, abs=1e-6)

    def test_returns_nan_for_empty_input(self):
        reference = np.array([1.0, 2.0, 3.0])
        comparison = np.array([np.nan, np.inf])

        assert np.isnan(population_stability_index(reference, comparison))

    def test_returns_nan_when_reference_has_no_spread(self):
        reference = np.full(100, 5.0)
        comparison = np.array([5.0, 6.0, 7.0])

        assert np.isnan(population_stability_index(reference, comparison))

    def test_out_of_range_comparison_values_still_count_as_drift(self):
        reference = np.linspace(0, 100, 1000)
        # Every comparison value is far outside the reference's real
        # observed range -- should register as real drift, not be
        # silently dropped by open-ended bin edges.
        comparison = np.full(1000, 1000.0)

        psi = population_stability_index(reference, comparison)

        assert psi > PSI_MODERATE_THRESHOLD


class TestFeatureDriftReport:
    def test_psi_severity_bands(self):
        assert (
            FeatureDriftReport(
                "f",
                psi=0.05,
                ks_statistic=0,
                ks_pvalue=1,
                reference_n=1,
                comparison_n=1,
            ).psi_severity
            == "none"
        )
        assert (
            FeatureDriftReport(
                "f",
                psi=0.15,
                ks_statistic=0,
                ks_pvalue=1,
                reference_n=1,
                comparison_n=1,
            ).psi_severity
            == "moderate"
        )
        assert (
            FeatureDriftReport(
                "f", psi=0.3, ks_statistic=0, ks_pvalue=1, reference_n=1, comparison_n=1
            ).psi_severity
            == "major"
        )

    def test_psi_severity_unknown_for_nan(self):
        report = FeatureDriftReport(
            "f",
            psi=float("nan"),
            ks_statistic=0,
            ks_pvalue=1,
            reference_n=0,
            comparison_n=0,
        )

        assert report.psi_severity == "unknown"

    def test_ks_significant(self):
        significant = FeatureDriftReport(
            "f",
            psi=0.0,
            ks_statistic=0.5,
            ks_pvalue=0.001,
            reference_n=10,
            comparison_n=10,
        )
        not_significant = FeatureDriftReport(
            "f",
            psi=0.0,
            ks_statistic=0.01,
            ks_pvalue=0.9,
            reference_n=10,
            comparison_n=10,
        )

        assert significant.ks_significant() is True
        assert not_significant.ks_significant() is False

    def test_ks_significant_is_false_for_nan_pvalue(self):
        report = FeatureDriftReport(
            "f",
            psi=0.0,
            ks_statistic=float("nan"),
            ks_pvalue=float("nan"),
            reference_n=0,
            comparison_n=0,
        )

        assert report.ks_significant() is False


class TestComputeFeatureDrift:
    def test_produces_one_report_per_shared_column(self):
        rng = np.random.default_rng(0)
        reference = pd.DataFrame(
            {
                "a": rng.normal(size=500),
                "b": rng.normal(size=500),
            }
        )
        comparison = pd.DataFrame(
            {
                "a": rng.normal(size=500),
                "b": rng.normal(loc=5, size=500),
            }
        )

        reports = compute_feature_drift(reference, comparison, ["a", "b"])

        assert {r.feature for r in reports} == {"a", "b"}

    def test_skips_columns_missing_from_either_frame(self):
        reference = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        comparison = pd.DataFrame({"a": [1.0, 2.0], "b": [4.0, 5.0]})

        reports = compute_feature_drift(reference, comparison, ["a", "b", "c"])

        assert {r.feature for r in reports} == {"a"}

    def test_a_real_shift_is_detected_by_both_metrics(self):
        rng = np.random.default_rng(0)
        reference = pd.DataFrame({"x": rng.normal(loc=0, scale=1, size=1000)})
        comparison = pd.DataFrame({"x": rng.normal(loc=5, scale=1, size=1000)})

        [report] = compute_feature_drift(reference, comparison, ["x"])

        assert report.psi_severity == "major"
        assert report.ks_significant() is True
        assert report.reference_n == 1000
        assert report.comparison_n == 1000

    def test_no_real_shift_is_not_flagged(self):
        rng = np.random.default_rng(0)
        shared = rng.normal(loc=0, scale=1, size=2000)
        reference = pd.DataFrame({"x": shared[:1000]})
        comparison = pd.DataFrame({"x": shared[1000:]})

        [report] = compute_feature_drift(reference, comparison, ["x"])

        assert report.psi_severity == "none"
        assert report.ks_significant() is False
