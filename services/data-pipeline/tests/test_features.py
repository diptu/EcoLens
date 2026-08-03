import numpy as np
import pandas as pd
import pytest

from app.service.ml import features


def _demand_df(n_per_region: int = 20, regions: tuple[str, ...] = ("NSW1", "QLD1")):
    ts = pd.date_range("2026-01-01", periods=n_per_region, freq="5min", tz="UTC")
    frames = []
    for i, region in enumerate(regions):
        frames.append(
            pd.DataFrame(
                {
                    "ts": ts,
                    "region": region,
                    "demand_mw": np.arange(n_per_region, dtype=float) + i * 1000,
                    "price_mwh": 50.0,
                    "total_generation_mw": 5000.0,
                    "total_renewable_mw": 1000.0,
                    "temp_c": 20.0,
                    "apparent_temp_c": 21.0,
                    "humidity_pct": 50.0,
                    "wind_speed_kmh": 10.0,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


# ── add_cyclical ─────────────────────────────────────────────────────


def test_add_cyclical_unit_circle_identity():
    df = pd.DataFrame({"hour": [0, 6, 12, 18]})

    out = features.add_cyclical(df, "hour", period=24)

    assert (
        (out["hour_sin"] ** 2 + out["hour_cos"] ** 2)
        .apply(lambda v: v == pytest.approx(1.0))
        .all()
    )


def test_add_cyclical_known_values():
    df = pd.DataFrame({"hour": [0, 6, 12, 18]})

    out = features.add_cyclical(df, "hour", period=24)

    assert out.loc[0, "hour_sin"] == pytest.approx(0.0, abs=1e-9)
    assert out.loc[0, "hour_cos"] == pytest.approx(1.0)
    assert out.loc[2, "hour_sin"] == pytest.approx(0.0, abs=1e-9)
    assert out.loc[2, "hour_cos"] == pytest.approx(-1.0)


def test_add_cyclical_does_not_mutate_input():
    df = pd.DataFrame({"hour": [0, 6]})
    features.add_cyclical(df, "hour", period=24)

    assert "hour_sin" not in df.columns


# ── add_calendar_features ───────────────────────────────────────────


def test_add_calendar_features_extracts_calendar_fields():
    # 2026-01-05 is a Monday
    ts = pd.date_range("2026-01-05", periods=8, freq="1D", tz="UTC")
    df = pd.DataFrame({"ts": ts, "region": "NSW1"})

    out = features.add_calendar_features(df)

    assert list(out["day_of_week"]) == [0, 1, 2, 3, 4, 5, 6, 0]
    assert list(out["is_weekend"]) == [
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        False,
    ]
    assert set(out["month"]) == {1}
    for col in (
        "hour_sin",
        "hour_cos",
        "day_of_week_sin",
        "day_of_week_cos",
        "month_sin",
        "month_cos",
    ):
        assert col in out.columns


def test_add_calendar_features_without_holidays_is_never_holiday():
    df = pd.DataFrame(
        {"ts": pd.date_range("2026-01-01", periods=3, tz="UTC"), "region": "NSW1"}
    )

    out = features.add_calendar_features(df, holidays=None)

    assert not out["is_holiday"].any()


def test_add_calendar_features_region_specific_holidays():
    df = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-01-01", "2026-01-01"], utc=True),
            "region": ["NSW1", "QLD1"],
        }
    )
    holidays = pd.DataFrame({"region": ["NSW1"], "date": ["2026-01-01"]})

    out = features.add_calendar_features(df, holidays=holidays)

    assert out.loc[out["region"] == "NSW1", "is_holiday"].iloc[0]
    assert not out.loc[out["region"] == "QLD1", "is_holiday"].iloc[0]


def test_add_calendar_features_date_only_holidays_apply_to_every_region():
    df = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-01-01", "2026-01-01"], utc=True),
            "region": ["NSW1", "QLD1"],
        }
    )
    holidays = pd.DataFrame({"date": ["2026-01-01"]})

    out = features.add_calendar_features(df, holidays=holidays)

    assert out["is_holiday"].all()


# ── add_lag_and_rolling ──────────────────────────────────────────────


def test_add_lag_and_rolling_does_not_leak_across_regions():
    # Interleaved on purpose -- a naive (non-grouped) shift(1) would give
    # QLD1's first row NSW1's last value as its lag.
    df = pd.DataFrame(
        {
            "ts": pd.to_datetime(
                [
                    "2026-01-01T00:00",
                    "2026-01-01T00:00",
                    "2026-01-01T00:05",
                    "2026-01-01T00:05",
                ],
                utc=True,
            ),
            "region": ["NSW1", "QLD1", "NSW1", "QLD1"],
            "demand_mw": [100.0, 900.0, 110.0, 910.0],
        }
    )

    out = features.add_lag_and_rolling(df, lags=(1,), windows=())

    nsw1_second_row = out[(out["region"] == "NSW1") & (out["demand_mw"] == 110.0)]
    assert nsw1_second_row["demand_mw_lag_1"].iloc[0] == pytest.approx(100.0)


def test_add_lag_and_rolling_warmup_is_nan():
    df = pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=5, freq="5min", tz="UTC"),
            "region": "NSW1",
            "demand_mw": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )

    out = features.add_lag_and_rolling(df, lags=(2,), windows=())

    assert out["demand_mw_lag_2"].iloc[:2].isna().all()
    assert out["demand_mw_lag_2"].iloc[2] == pytest.approx(10.0)


def test_add_lag_and_rolling_excludes_current_row():
    df = pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=4, freq="5min", tz="UTC"),
            "region": "NSW1",
            "demand_mw": [10.0, 20.0, 30.0, 40.0],
        }
    )

    out = features.add_lag_and_rolling(df, lags=(), windows=(2,))

    # Row index 2 (value 30.0): rolling mean over the *previous* up-to-2
    # values (10, 20) = 15.0, not (20, 30) = 25.0.
    assert out["demand_mw_rolling_mean_2"].iloc[2] == pytest.approx(15.0)


# ── add_weather_derived ──────────────────────────────────────────────


def test_add_weather_derived_heating_and_cooling_degrees():
    df = pd.DataFrame(
        {"temp_c": [5.0, 18.0, 30.0], "apparent_temp_c": [3.0, 18.0, 33.0]}
    )

    out = features.add_weather_derived(df)

    assert list(out["heating_degrees"]) == [13.0, 0.0, 0.0]
    assert list(out["cooling_degrees"]) == [0.0, 0.0, 12.0]
    assert list(out["apparent_temp_deviation_c"]) == [-2.0, 0.0, 3.0]


def test_add_weather_derived_noop_without_temp_column():
    df = pd.DataFrame({"humidity_pct": [50.0]})

    out = features.add_weather_derived(df)

    assert "heating_degrees" not in out.columns


# ── add_cross_region_context ─────────────────────────────────────────


def test_add_cross_region_context_sums_and_shares_across_regions():
    df = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-01-01T00:00"] * 2, utc=True),
            "region": ["NSW1", "QLD1"],
            "demand_mw": [300.0, 700.0],
        }
    )

    out = features.add_cross_region_context(df)

    assert (out["total_demand_all_regions_mw"] == 1000.0).all()
    assert out.loc[out["region"] == "NSW1", "demand_share_of_total"].iloc[
        0
    ] == pytest.approx(0.3)
    assert out.loc[out["region"] == "QLD1", "demand_share_of_total"].iloc[
        0
    ] == pytest.approx(0.7)


def test_add_cross_region_context_guards_zero_total():
    df = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-01-01T00:00"], utc=True),
            "region": ["WEM"],
            "demand_mw": [0.0],
        }
    )

    out = features.add_cross_region_context(df)

    assert pd.isna(out["demand_share_of_total"].iloc[0])


# ── build_features (end to end) ──────────────────────────────────────


def test_build_features_produces_every_declared_feature_column():
    df = _demand_df()

    out = features.build_features(df)

    missing = set(features.FEATURE_COLUMNS) - set(out.columns)
    assert not missing
    assert features.TARGET_COLUMN in out.columns


def test_build_features_keeps_regions_independent_after_full_pipeline():
    df = _demand_df(n_per_region=10, regions=("NSW1", "QLD1"))

    out = features.build_features(df)

    # QLD1's demand starts at 1000 -- a lag/rolling feature leaking from
    # NSW1 (which starts at 0) would show up as a suspiciously small
    # early value for QLD1's rolling mean.
    qld_first_valid = (
        out[out["region"] == "QLD1"]["demand_mw_rolling_mean_6"].dropna().iloc[0]
    )
    assert qld_first_valid >= 1000.0


# ── module constants ─────────────────────────────────────────────────


def test_feature_columns_and_numeric_columns_are_consistent():
    assert len(features.FEATURE_COLUMNS) == len(set(features.FEATURE_COLUMNS))
    assert set(features.NUMERIC_COLUMNS).issubset(set(features.FEATURE_COLUMNS))
    assert features.TARGET_COLUMN not in features.FEATURE_COLUMNS
