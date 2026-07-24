"""Tests for ecolens.forecasting.features (ECO-110)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ecolens.forecasting.features import (
    FEATURE_COLUMNS,
    TARGET_INDEX,
    FeatureScaler,
    build_windowed_dataset,
)


def _synthetic_snapshot(
    *, regions: tuple[str, ...], n: int, seed: int = 0
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for region in regions:
        ts = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
        df = pd.DataFrame({"ts_30": ts, "region": region})
        for col in FEATURE_COLUMNS:
            if col in ("is_holiday", "is_weekend"):
                df[col] = rng.integers(0, 2, size=n)
            else:
                df[col] = rng.normal(size=n)
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


class TestBuildWindowedDataset:
    def test_shapes(self):
        df = _synthetic_snapshot(regions=("NSW1", "VIC1"), n=500)
        ds = build_windowed_dataset(df, lookback=48, horizon=48)

        for split in (ds.train, ds.val, ds.calibration, ds.test):
            assert split.x.shape[1] == 48
            assert split.x.shape[2] == len(FEATURE_COLUMNS)
            assert split.y.shape[1] == 48
            assert (
                split.x.shape[0]
                == split.y.shape[0]
                == len(split.as_of)
                == len(split.region)
            )

    def test_splits_are_nonempty_and_chronological_per_region(self):
        df = _synthetic_snapshot(regions=("NSW1",), n=500)
        ds = build_windowed_dataset(df, lookback=48, horizon=48)

        assert len(ds.train.x) > 0
        assert len(ds.val.x) > 0
        assert len(ds.calibration.x) > 0
        assert len(ds.test.x) > 0

        # train's latest window must end no later than val's earliest.
        assert ds.train.as_of.max() <= ds.val.as_of.min()
        assert ds.val.as_of.max() <= ds.calibration.as_of.min()
        assert ds.calibration.as_of.max() <= ds.test.as_of.min()

    def test_scaler_fit_only_on_train(self):
        df = _synthetic_snapshot(regions=("NSW1",), n=500)
        ds = build_windowed_dataset(df, lookback=48, horizon=48)

        train_flat = ds.train.x.numpy().reshape(-1, len(FEATURE_COLUMNS))
        # Scaled train data should be ~standard-normal since the scaler
        # was fit on exactly this data.
        assert np.allclose(train_flat.mean(axis=0), 0, atol=0.15)
        assert np.allclose(train_flat.std(axis=0), 1, atol=0.15)

    def test_target_scaling_round_trips(self):
        df = _synthetic_snapshot(regions=("NSW1",), n=500)
        ds = build_windowed_dataset(df, lookback=48, horizon=48)

        # y is scaled by the *target feature's* mean/std -- inverse
        # transforming it should recover values in the original range.
        recovered = ds.scaler.inverse_transform_target(ds.test.y.numpy())
        original_target_std = df["demand_mw"].std()
        assert recovered.std() == pytest.approx(original_target_std, rel=0.5)

    def test_no_nans_anywhere(self):
        df = _synthetic_snapshot(regions=("NSW1", "QLD1"), n=400)
        ds = build_windowed_dataset(df, lookback=48, horizon=48)
        for split in (ds.train, ds.val, ds.calibration, ds.test):
            assert not np.isnan(split.x.numpy()).any()
            assert not np.isnan(split.y.numpy()).any()

    def test_missing_columns_raises(self):
        df = _synthetic_snapshot(regions=("NSW1",), n=200).drop(columns=["temp_c"])
        with pytest.raises(ValueError, match="missing expected columns"):
            build_windowed_dataset(df, lookback=48, horizon=48)

    def test_insufficient_history_raises(self):
        df = _synthetic_snapshot(regions=("NSW1",), n=10)
        with pytest.raises(ValueError, match="not enough history"):
            build_windowed_dataset(df, lookback=48, horizon=48)

    def test_drops_rows_with_nulls_before_windowing(self):
        df = _synthetic_snapshot(regions=("NSW1",), n=500)
        df.loc[0, "temp_c"] = np.nan  # simulate the one-row rolling-avg gap
        ds = build_windowed_dataset(df, lookback=48, horizon=48)
        for split in (ds.train, ds.val, ds.calibration, ds.test):
            assert not np.isnan(split.x.numpy()).any()

    def test_target_index_matches_demand_mw(self):
        assert FEATURE_COLUMNS[TARGET_INDEX] == "demand_mw"

    def test_given_scaler_is_used_verbatim_not_refit(self):
        # An intentionally-wrong scaler (way off from this df's actual
        # mean/std) -- if build_windowed_dataset refit its own instead of
        # using this one, the assertions below would fail.
        df = _synthetic_snapshot(regions=("NSW1",), n=500)
        wrong_scaler = FeatureScaler(
            mean=np.full(len(FEATURE_COLUMNS), 1000.0),
            std=np.full(len(FEATURE_COLUMNS), 50.0),
            columns=FEATURE_COLUMNS,
        )
        ds = build_windowed_dataset(df, lookback=48, horizon=48, scaler=wrong_scaler)

        assert ds.scaler is wrong_scaler
        # Real data (~standard normal per _synthetic_snapshot) scaled by
        # mean=1000/std=50 lands far from zero, not ~standard-normal like
        # test_scaler_fit_only_on_train's freshly-fit-scaler case.
        train_flat = ds.train.x.numpy().reshape(-1, len(FEATURE_COLUMNS))
        assert not np.allclose(train_flat.mean(axis=0), 0, atol=0.5)

    def test_omitted_scaler_still_fits_fresh(self):
        # Default (no scaler passed) behavior is unchanged.
        df = _synthetic_snapshot(regions=("NSW1",), n=500)
        ds = build_windowed_dataset(df, lookback=48, horizon=48)
        assert ds.scaler is not None
