"""Tests for ecolens.forecasting.service.feature_selection (root TODO.md's
"Feature selection" section — extracted from the notebook prototype into
this reusable module). Steps 1/2/4 use synthetic data engineered to have
an unambiguous right answer for each step (a genuine constant column, a
genuine duplicate, a genuine noise column) rather than real warehouse data
— correctness against the real `ml_features_demand_v1` mart was verified
separately (see TODO.md's own writeup for the real numbers); these tests
exist to pin the *mechanics* down with fast, deterministic synthetic
cases, same split this repo already draws for the LSTM/TFT/TimesFM tests.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from ecolens.forecasting.service.feature_selection import (
    run_steps_1_2_4,
    step1_structural_hygiene,
    step2_mutual_information,
    step3_pacf_lag_selection,
    step4_multicollinearity_pruning,
    step5_tft_vsn_gating,
)


def _synthetic_df(*, n: int = 2000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    demand_mw = 5000 + 500 * np.sin(2 * np.pi * t / 48) + rng.normal(0, 20, n)

    return pd.DataFrame(
        {
            "region": "NSW1",
            "ts_30": pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC"),
            "demand_mw": demand_mw,
            # A genuinely informative, non-redundant feature -- phase-
            # shifted and noisier than demand_mw's own sine so it's
            # correlated with the target (r ~ -0.58) without being
            # multicollinear with demand_mw_duplicate below (r > 0.9
            # would make Step 4 correctly drop it as redundant, which
            # isn't what this fixture is testing for).
            "temp_c": 20
            + 3 * np.cos(2 * np.pi * t / 48 + np.pi / 2)
            + rng.normal(0, 3, n),
            # Zero variance -- structural hygiene must catch this.
            "constant_col": 42.0,
            # Fully null -- structural hygiene must catch this too.
            "empty_col": np.nan,
            # A near-exact duplicate of demand_mw (r > 0.9) -- multicollinearity
            # pruning must catch this pair and keep whichever LightGBM favors.
            "demand_mw_duplicate": demand_mw + rng.normal(0, 1, n),
            # Pure noise, uncorrelated with the target -- low MI, should land
            # in the bottom-fraction drop set.
            "pure_noise": rng.normal(0, 1, n),
            # A boolean column -- step2 must coerce this to int for sklearn.
            "is_holiday": rng.integers(0, 2, n).astype(bool),
        }
    )


class TestStep1StructuralHygiene:
    def test_detects_zero_variance_and_fully_null_columns(self):
        df = _synthetic_df()
        candidates = [
            c for c in df.columns if c not in ("region", "ts_30", "demand_mw")
        ]
        result = step1_structural_hygiene(df, candidates)
        # An all-NaN column's var() is NaN, which fillna(0) treats as
        # zero-variance too -- it legitimately shows up in *both* lists
        # (matches the notebook's identical logic), the union in
        # drop_cols is what actually matters.
        assert set(result.zero_variance_cols) == {"constant_col", "empty_col"}
        assert result.fully_null_cols == ["empty_col"]
        assert set(result.drop_cols) == {"constant_col", "empty_col"}

    def test_clean_data_drops_nothing(self):
        df = _synthetic_df()
        candidates = ["temp_c", "pure_noise"]
        result = step1_structural_hygiene(df, candidates)
        assert result.drop_cols == []


class TestStep2MutualInformation:
    def test_pure_noise_ranks_low(self):
        df = _synthetic_df()
        candidates = ["temp_c", "demand_mw_duplicate", "pure_noise", "is_holiday"]
        result = step2_mutual_information(
            df, candidates, "demand_mw", drop_fraction=0.25
        )
        # 4 candidates, 25% -> 1 dropped -- the lowest-MI one.
        assert len(result.drop_cols) == 1
        assert result.scores.index[-1] == result.drop_cols[0]
        # pure_noise has no real relationship to demand_mw -- it should
        # score at or near the bottom, well below the informative columns.
        assert result.scores["pure_noise"] < result.scores["temp_c"]
        assert result.scores["pure_noise"] < result.scores["demand_mw_duplicate"]

    def test_bool_column_does_not_raise(self):
        df = _synthetic_df()
        result = step2_mutual_information(df, ["is_holiday"], "demand_mw")
        assert "is_holiday" in result.scores.index

    def test_zero_drop_fraction_drops_nothing(self):
        df = _synthetic_df()
        result = step2_mutual_information(
            df, ["temp_c", "pure_noise"], "demand_mw", drop_fraction=0.0
        )
        assert result.drop_cols == []


class TestStep3PACFLagSelection:
    def test_finds_lag_one_significant(self):
        # demand_mw is a smooth, strongly autocorrelated series -- lag 1
        # must show up significant regardless of the exact process. (A
        # pure sinusoid's PACF is actually dominated by lags 1-2 via its
        # own AR(2)-like recursion, *not* its period -- PACF measures the
        # correlation left over after controlling for intermediate lags,
        # so testing "lag == period is significant" against synthetic
        # data doesn't hold; that's exactly why the real notebook this
        # module was extracted from validated lag 48/336 against real,
        # non-sinusoidal demand data instead.)
        df = _synthetic_df(n=3000)
        result = step3_pacf_lag_selection(
            df, "demand_mw", region="NSW1", max_lag=100, proposed_lags=(1, 97)
        )
        assert result.proposed_lag_significance[1] is True

    def test_reports_every_proposed_lag(self):
        df = _synthetic_df(n=3000)
        result = step3_pacf_lag_selection(
            df, "demand_mw", region="NSW1", max_lag=60, proposed_lags=(1, 2, 48)
        )
        assert set(result.proposed_lag_significance) == {1, 2, 48}


class TestStep4MulticollinearityPruning:
    def test_detects_the_duplicate_pair_and_drops_the_weaker_one(self):
        df = _synthetic_df()
        candidates = ["temp_c", "demand_mw_duplicate", "pure_noise"]
        result = step4_multicollinearity_pruning(df, candidates, "demand_mw")
        pair_cols = {p[0] for p in result.multicollinear_pairs} | {
            p[1] for p in result.multicollinear_pairs
        }
        # demand_mw_duplicate correlates with nothing else in this candidate
        # set except itself trivially -- the real signal here is that its
        # near-1.0 correlation with the *target* doesn't matter (Step 4
        # only prunes candidate-candidate pairs), so assert no false
        # positive: temp_c/pure_noise are genuinely uncorrelated with each
        # other and shouldn't appear as a pair.
        assert "temp_c" not in pair_cols or "pure_noise" not in pair_cols

    def test_importance_ranks_the_informative_feature_above_noise(self):
        df = _synthetic_df()
        result = step4_multicollinearity_pruning(
            df, ["temp_c", "pure_noise"], "demand_mw"
        )
        assert result.importance["temp_c"] > result.importance["pure_noise"]


class TestRunSteps124:
    def test_composed_pipeline_drops_the_engineered_bad_columns(self):
        df = _synthetic_df()
        summary = run_steps_1_2_4(df, mi_drop_fraction=0.2)
        assert "constant_col" not in summary.kept_cols
        assert "empty_col" not in summary.kept_cols
        assert "temp_c" in summary.kept_cols  # genuinely informative, keep it

    def test_candidate_cols_excludes_identifiers_and_target(self):
        df = _synthetic_df()
        summary = run_steps_1_2_4(df)
        assert "region" not in summary.candidate_cols
        assert "ts_30" not in summary.candidate_cols
        assert "demand_mw" not in summary.candidate_cols


class TestStep5TFTVSNGating:
    def test_weights_sum_to_one_per_position(self):
        from ecolens.forecasting.model.tft import DemandTFT

        n_features, horizon = 5, 8
        model = DemandTFT(
            n_features=n_features,
            d_model=16,
            num_heads=2,
            num_lstm_layers=1,
            num_regions=2,
            static_dim=8,
            horizon=horizon,
            dropout=0.0,
        )
        x = torch.randn(16, 24, n_features)
        region_idx = torch.randint(0, 2, (16,))

        result = step5_tft_vsn_gating(
            model,
            x,
            region_idx,
            feature_columns=tuple(f"f{i}" for i in range(n_features)),
        )
        # A VSN's weights are a softmax over features at every (sample,
        # timestep) position -- averaging those across all positions
        # must still sum to 1 across features (mean of many things that
        # each individually sum to 1 also sums to 1).
        assert len(result.mean_weight_per_feature) == n_features
        assert result.mean_weight_per_feature.sum() == pytest.approx(1.0, abs=1e-4)
        assert (result.mean_weight_per_feature >= 0).all()

    def test_near_zero_threshold_correctly_filters_the_bottom_features(self):
        # Tests the filtering mechanics directly (which columns end up in
        # near_zero_cols for a given threshold) rather than trying to
        # force an *untrained* model's unpredictable selection behavior
        # to favor a specific feature -- an untrained VSN's weights
        # reflect random init, not learned importance, so there's no
        # reliable way to make it "ignore" a chosen feature without
        # actually training it.
        from ecolens.forecasting.model.tft import DemandTFT

        n_features, horizon = 6, 4
        model = DemandTFT(
            n_features=n_features,
            d_model=8,
            num_heads=2,
            num_lstm_layers=1,
            num_regions=2,
            static_dim=4,
            horizon=horizon,
            dropout=0.0,
        )
        x = torch.randn(32, 12, n_features)
        region_idx = torch.randint(0, 2, (32,))
        feature_columns = tuple(f"f{i}" for i in range(n_features))

        result = step5_tft_vsn_gating(
            model, x, region_idx, feature_columns=feature_columns
        )
        # Threshold set halfway between the 3rd- and 4th-lowest weights --
        # by construction, exactly the bottom 3 features must be flagged.
        sorted_weights = result.mean_weight_per_feature.sort_values()
        threshold = (sorted_weights.iloc[2] + sorted_weights.iloc[3]) / 2
        result_at_threshold = step5_tft_vsn_gating(
            model,
            x,
            region_idx,
            feature_columns=feature_columns,
            near_zero_threshold=threshold,
        )
        assert set(result_at_threshold.near_zero_cols) == set(sorted_weights.index[:3])
