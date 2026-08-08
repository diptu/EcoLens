from __future__ import annotations

import pytest

from app.service.ml.emission_factors import GENERATION_BUCKET_FUEL_TYPES, compute_bucket_factors


class TestComputeBucketFactors:
    def test_single_member_bucket_passes_through_exactly(self):
        intensity = {"coal": 910.0, "gas": 490.0, "wind": 4.0}
        weights = {"coal": 5000.0, "gas": 3000.0, "wind": 500.0}

        result = compute_bucket_factors(intensity, weights)

        assert result["coal"] == pytest.approx(910.0)
        assert result["gas"] == pytest.approx(490.0)
        assert result["wind"] == pytest.approx(4.0)

    def test_multi_member_bucket_is_generation_weighted_not_a_flat_average(self):
        # "other" = hydro(5) + biomass(0) + distillate(770) + pumped_hydro(0)
        #   + battery_discharge(0). A flat average would be 155; weighting
        #   by real generation volume (distillate barely dispatched) should
        #   land close to hydro's own factor instead.
        intensity = {
            "coal": 910.0, "gas": 490.0, "wind": 4.0,
            "solar_utility": 5.0, "solar_rooftop": 5.0,
            "hydro": 5.0, "biomass": 0.0, "distillate": 770.0,
            "pumped_hydro": 0.0, "battery_discharge": 0.0,
        }
        # Real average MW from services/ingestion's master.duckdb (a full
        # year of real per-region history) -- distillate is a rarely-
        # dispatched peaking fuel, hydro dominates "other" by volume.
        weights = {
            "hydro": 265.51, "biomass": 13.98, "distillate": 0.39,
            "pumped_hydro": 32.13, "battery_discharge": 68.37,
            "solar_utility": 385.12, "solar_rooftop": 672.16,
            "coal": 5000.0, "gas": 3000.0, "wind": 500.0,
        }

        result = compute_bucket_factors(intensity, weights)

        assert result["other"] == pytest.approx(4.2765, rel=1e-3)
        assert result["other"] < 10.0  # nowhere near the flat-average 155
        assert result["solar"] == pytest.approx(5.0)

    def test_falls_back_to_unweighted_mean_when_no_real_weight_exists(self):
        intensity = {"hydro": 5.0, "distillate": 770.0}
        weights: dict[str, float] = {}  # no real generation data yet

        result = compute_bucket_factors(intensity, weights)

        # honest fallback: plain mean of the 2 members, not a crash or a 0
        assert result["other"] == pytest.approx((5.0 + 770.0) / 2)

    def test_missing_fuel_types_are_skipped_not_fabricated(self):
        # Only coal/gas/wind present -- solar/other buckets have no
        # member factors available at all.
        intensity = {"coal": 910.0, "gas": 490.0, "wind": 4.0}
        weights = {"coal": 1.0, "gas": 1.0, "wind": 1.0}

        result = compute_bucket_factors(intensity, weights)

        assert set(result.keys()) == {"coal", "gas", "wind"}

    def test_bucket_names_match_the_model_generation_head_order(self):
        assert set(GENERATION_BUCKET_FUEL_TYPES.keys()) == {
            "coal", "gas", "wind", "solar", "other",
        }
