import numpy as np
import pandas as pd
import pytest
import torch

from app.service.ml import data as ml_data


def _features_df(n_per_region: int = 20, regions: tuple[str, ...] = ("NSW1", "QLD1")):
    ts = pd.date_range("2026-01-01", periods=n_per_region, freq="5min", tz="UTC")
    frames = []
    for i, region in enumerate(regions):
        frames.append(
            pd.DataFrame(
                {
                    "ts": ts,
                    "region": region,
                    "demand_mw": np.arange(n_per_region, dtype=float) + i * 1000,
                    "feat_a": np.arange(n_per_region, dtype=float) + i * 100,
                    "feat_b": np.linspace(0, 1, n_per_region) + i,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


# ── split_by_time ────────────────────────────────────────────────────


def test_split_by_time_is_chronological_not_shuffled():
    df = _features_df(n_per_region=100, regions=("NSW1",))

    split = ml_data.split_by_time(df, train_frac=0.7, val_frac=0.15)

    assert split.train["ts"].max() < split.val["ts"].min()
    assert split.val["ts"].max() < split.test["ts"].min()


def test_split_by_time_covers_every_row_exactly_once():
    df = _features_df(n_per_region=50, regions=("NSW1", "QLD1"))

    split = ml_data.split_by_time(df)

    assert len(split.train) + len(split.val) + len(split.test) == len(df)


def test_split_by_time_boundary_is_shared_across_regions():
    df = _features_df(n_per_region=50, regions=("NSW1", "QLD1"))

    split = ml_data.split_by_time(df)

    # Same global cutoff -- both regions' train sets end at the same ts.
    train_end_by_region = split.train.groupby("region")["ts"].max()
    assert train_end_by_region.nunique() == 1


def test_split_by_time_rejects_invalid_fractions():
    df = _features_df()
    with pytest.raises(ValueError, match="train_frac"):
        ml_data.split_by_time(df, train_frac=0.8, val_frac=0.3)


# ── fit_scalers / apply_scalers ──────────────────────────────────────


def test_fit_scalers_is_fit_per_region():
    df = _features_df(n_per_region=30, regions=("NSW1", "QLD1"))

    scalers = ml_data.fit_scalers(df, columns=["feat_a"])

    assert set(scalers) == {"NSW1", "QLD1"}
    # Regions have disjoint feat_a ranges -- means must differ.
    assert scalers["NSW1"].mean_[0] != scalers["QLD1"].mean_[0]


def test_fit_scalers_excludes_rows_with_nan():
    df = _features_df(n_per_region=10, regions=("NSW1",))
    df.loc[0, "feat_a"] = np.nan

    scalers = ml_data.fit_scalers(df, columns=["feat_a"])

    assert scalers["NSW1"].n_samples_seen_ == 9


def test_fit_scalers_skips_region_with_no_complete_rows():
    df = _features_df(n_per_region=3, regions=("NSW1",))
    df["feat_a"] = np.nan

    scalers = ml_data.fit_scalers(df, columns=["feat_a"])

    assert "NSW1" not in scalers


def test_apply_scalers_transforms_matching_region_rows():
    df = _features_df(n_per_region=30, regions=("NSW1", "QLD1"))
    scalers = ml_data.fit_scalers(df, columns=["feat_a"])

    out = ml_data.apply_scalers(df, scalers, columns=["feat_a"])

    # A fitted StandardScaler applied to its own training data has ~0 mean.
    assert out.loc[out["region"] == "NSW1", "feat_a"].mean() == pytest.approx(
        0.0, abs=1e-9
    )
    assert out.loc[out["region"] == "QLD1", "feat_a"].mean() == pytest.approx(
        0.0, abs=1e-9
    )


def test_apply_scalers_leaves_unscalable_rows_untouched():
    df = _features_df(n_per_region=10, regions=("NSW1",))
    df.loc[0, "feat_a"] = np.nan
    original_value = df.loc[0, "feat_a"]
    scalers = ml_data.fit_scalers(df, columns=["feat_a"])

    out = ml_data.apply_scalers(df, scalers, columns=["feat_a"])

    assert pd.isna(out.loc[0, "feat_a"]) == pd.isna(original_value)


def test_apply_scalers_ignores_region_with_no_fitted_scaler():
    df = _features_df(n_per_region=5, regions=("WEM",))
    out = ml_data.apply_scalers(df, scalers={}, columns=["feat_a"])

    pd.testing.assert_series_equal(out["feat_a"], df["feat_a"])


# ── DemandDataset ─────────────────────────────────────────────────────


def test_demand_dataset_produces_expected_sample_count():
    df = _features_df(n_per_region=20, regions=("NSW1",))

    ds = ml_data.DemandDataset(
        df, feature_columns=["feat_a", "feat_b"], lookback=5, horizon=3
    )

    # 20 rows, window span 8 -> 13 possible windows, none contain NaN.
    assert len(ds) == 13


def test_demand_dataset_item_shapes():
    df = _features_df(n_per_region=20, regions=("NSW1",))

    ds = ml_data.DemandDataset(
        df, feature_columns=["feat_a", "feat_b"], lookback=5, horizon=3
    )
    x, y = ds[0]

    assert x.shape == (5, 2)
    assert y.shape == (3,)
    assert isinstance(x, torch.Tensor)


def test_demand_dataset_first_window_matches_expected_values():
    df = _features_df(n_per_region=20, regions=("NSW1",))

    ds = ml_data.DemandDataset(
        df, feature_columns=["feat_a"], target_col="demand_mw", lookback=5, horizon=3
    )
    x, y = ds[0]

    assert x.flatten().tolist() == pytest.approx([0.0, 1.0, 2.0, 3.0, 4.0])
    assert y.tolist() == pytest.approx([5.0, 6.0, 7.0])


def test_demand_dataset_never_crosses_region_boundary():
    df = _features_df(n_per_region=10, regions=("NSW1", "QLD1"))

    ds = ml_data.DemandDataset(
        df, feature_columns=["feat_a"], target_col="demand_mw", lookback=4, horizon=2
    )

    # QLD1's demand starts at 1000 -- if a window straddled regions, some
    # sample's y would mix values below and above that boundary in a way
    # that couldn't happen from a single region's own arange().
    for _, y in ds:
        values = y.tolist()
        assert all(v < 1000 for v in values) or all(v >= 1000 for v in values)


def test_demand_dataset_drops_windows_with_nan():
    df = _features_df(n_per_region=10, regions=("NSW1",))
    df.loc[2, "feat_a"] = np.nan

    ds = ml_data.DemandDataset(df, feature_columns=["feat_a"], lookback=3, horizon=2)

    # Window span 5 -> 6 possible windows; the ones whose x includes row 2
    # (starts 0, 1, 2) are dropped, leaving 3.
    assert len(ds) == 3


def test_demand_dataset_too_short_group_yields_no_samples():
    df = _features_df(n_per_region=3, regions=("NSW1",))

    ds = ml_data.DemandDataset(df, feature_columns=["feat_a"], lookback=5, horizon=3)

    assert len(ds) == 0


# ── collate ──────────────────────────────────────────────────────────


def test_collate_stacks_batch_into_expected_shape():
    df = _features_df(n_per_region=20, regions=("NSW1",))
    ds = ml_data.DemandDataset(
        df, feature_columns=["feat_a", "feat_b"], lookback=5, horizon=3
    )
    batch = [ds[0], ds[1], ds[2]]

    x, y = ml_data.collate(batch)

    assert x.shape == (3, 5, 2)
    assert y.shape == (3, 3)


# ── load_training_data / load_holidays ──────────────────────────────────


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(
        self, demand_rows=(), holiday_rows=(), ml_features_v1_rows=(), imputed_frac=None
    ):
        self.demand_rows = list(demand_rows)
        self.holiday_rows = list(holiday_rows)
        self.ml_features_v1_rows = list(ml_features_v1_rows)
        self.imputed_frac = imputed_frac
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.queries.append((sql, params))
        if "ml_features_demand_v1" in sql and "frac" in sql:
            return _FakeResult([{"frac": self.imputed_frac}])
        if "ml_features_demand_v1" in sql:
            return _FakeResult(self.ml_features_v1_rows)
        if "fct_energy_demand" in sql:
            return _FakeResult(self.demand_rows)
        if "aemo_holidays" in sql:
            return _FakeResult(self.holiday_rows)
        raise AssertionError(f"unexpected query: {sql}")


class TestLoadTrainingData:
    pytestmark = [pytest.mark.anyio]

    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    async def test_queries_the_marts_schema_and_filters_by_region(self):
        session = _FakeSession(
            demand_rows=[
                {
                    "ts": pd.Timestamp("2026-01-01", tz="UTC"),
                    "region": "NSW1",
                    "demand_mw": 8000.0,
                    "price_mwh": 65.0,
                    "total_generation_mw": 9000.0,
                    "total_renewable_mw": 3000.0,
                    "temp_c": 22.0,
                    "apparent_temp_c": 23.0,
                    "humidity_pct": 50.0,
                    "wind_speed_kmh": 12.0,
                }
            ]
        )

        df = await ml_data.load_training_data(session, ["NSW1"])

        assert list(df.columns) == list(ml_data._TRAINING_COLUMNS)
        assert len(df) == 1
        assert df.iloc[0]["region"] == "NSW1"
        sql, params = session.queries[0]
        assert "raw_marts.fct_energy_demand" in sql
        assert params["regions"] == ["NSW1"]
        assert "since" not in params

    async def test_since_filter_is_applied_when_given(self):
        session = _FakeSession()
        since = pd.Timestamp("2026-01-01", tz="UTC")

        await ml_data.load_training_data(session, ["NSW1", "QLD1"], since=since)

        sql, params = session.queries[0]
        assert "ts >= :since" in sql
        assert params["since"] == since

    async def test_empty_result_still_has_expected_columns(self):
        session = _FakeSession(demand_rows=[])

        df = await ml_data.load_training_data(session, ["NSW1"])

        assert list(df.columns) == list(ml_data._TRAINING_COLUMNS)
        assert df.empty

    async def test_load_holidays_returns_date_region_frame(self):
        session = _FakeSession(
            holiday_rows=[{"date": pd.Timestamp("2026-01-01").date(), "region": "NSW1"}]
        )

        df = await ml_data.load_holidays(session)

        assert list(df.columns) == ["date", "region"]


# ── load_ml_features_v1_training_data / _imputed_fraction ──────────────


class TestLoadMlFeaturesV1TrainingData:
    pytestmark = [pytest.mark.anyio]

    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    async def test_queries_the_ml_schema_and_renames_renewable_column(self):
        session = _FakeSession(
            ml_features_v1_rows=[
                {
                    "ts": pd.Timestamp("2026-01-01", tz="UTC"),
                    "region": "NSW1",
                    "demand_mw": 8000.0,
                    "price_mwh": 65.0,
                    "total_generation_mw": 9000.0,
                    "total_renewable_mw": 3000.0,
                    "temp_c": 22.0,
                    "apparent_temp_c": 23.0,
                    "humidity_pct": 50.0,
                    "wind_speed_kmh": 12.0,
                }
            ]
        )

        df = await ml_data.load_ml_features_v1_training_data(session, ["NSW1"])

        # Same output shape as `load_training_data` -- required for
        # `build_features` to accept either source interchangeably.
        assert list(df.columns) == list(ml_data._TRAINING_COLUMNS)
        assert len(df) == 1
        sql, params = session.queries[0]
        assert "ml.ml_features_demand_v1" in sql
        assert "renewable_generation_mw AS total_renewable_mw" in sql
        assert params["regions"] == ["NSW1"]

    async def test_since_filter_is_applied_when_given(self):
        session = _FakeSession()
        since = pd.Timestamp("2026-01-01", tz="UTC")

        await ml_data.load_ml_features_v1_training_data(session, ["NSW1"], since=since)

        sql, params = session.queries[0]
        assert "ts >= :since" in sql
        assert params["since"] == since

    async def test_empty_result_still_has_expected_columns(self):
        session = _FakeSession(ml_features_v1_rows=[])

        df = await ml_data.load_ml_features_v1_training_data(session, ["NSW1"])

        assert list(df.columns) == list(ml_data._TRAINING_COLUMNS)
        assert df.empty


class TestLoadMlFeaturesV1ImputedFraction:
    pytestmark = [pytest.mark.anyio]

    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    async def test_returns_the_real_fraction(self):
        session = _FakeSession(imputed_frac=0.66)

        frac = await ml_data.load_ml_features_v1_imputed_fraction(session, ["NSW1"])

        assert frac == 0.66

    async def test_returns_zero_not_none_when_there_are_no_rows(self):
        session = _FakeSession(imputed_frac=None)

        frac = await ml_data.load_ml_features_v1_imputed_fraction(session, ["NSW1"])

        assert frac == 0.0
