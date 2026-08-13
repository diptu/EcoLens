from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from app.core.config import get_settings
from app.service import object_storage
from app.service.pipeline import ml_anomaly
from app.service.pipeline.duckdb_staging import stage_dataframe

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _staging_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_STAGING_DIR", str(tmp_path))
    get_settings.cache_clear()
    ml_anomaly.invalidate_cache()
    yield
    ml_anomaly.invalidate_cache()
    get_settings.cache_clear()


def _clustered_history(n: int, run_id: str = "history-run") -> None:
    """Tight cluster around plausible AEMO-NEM-shaped values -- enough
    real history for `train` to have something to fit against."""
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "demand_mw": rng.normal(8000, 50, n),
            "price_mwh": rng.normal(60, 5, n),
        }
    )
    stage_dataframe(df, "aemo_nem_dispatch", run_id)


class TestTrain:
    def test_returns_none_for_a_source_with_no_numeric_columns(self):
        _clustered_history(ml_anomaly.MIN_TRAINING_ROWS + 10)

        model = ml_anomaly.train("aemo_holidays", "aemo_holidays")

        assert model is None

    def test_returns_none_when_no_history_exists_yet(self):
        model = ml_anomaly.train("aemo_nem", "aemo_nem_dispatch")

        assert model is None

    def test_returns_none_below_min_training_rows(self):
        _clustered_history(ml_anomaly.MIN_TRAINING_ROWS - 1)

        model = ml_anomaly.train("aemo_nem", "aemo_nem_dispatch")

        assert model is None

    def test_fits_a_model_with_enough_real_history(self):
        n = ml_anomaly.MIN_TRAINING_ROWS + 20
        _clustered_history(n)

        model = ml_anomaly.train("aemo_nem", "aemo_nem_dispatch")

        assert model is not None
        assert model.source == "aemo_nem"
        assert set(model.columns) == {"demand_mw", "price_mwh"}
        assert model.rows_trained == n


class TestSaveAndLoadLocal:
    def test_roundtrips_through_disk(self):
        _clustered_history(ml_anomaly.MIN_TRAINING_ROWS + 5)
        model = ml_anomaly.train("aemo_nem", "aemo_nem_dispatch")
        assert model is not None

        path = ml_anomaly.save_local(model)
        assert path.exists()

        reloaded = ml_anomaly.load_local("aemo_nem")

        assert reloaded is not None
        assert reloaded.source == model.source
        assert reloaded.columns == model.columns
        assert reloaded.rows_trained == model.rows_trained

    def test_load_local_returns_none_when_nothing_saved_yet(self):
        assert ml_anomaly.load_local("aemo_nem") is None


class TestScore:
    def test_returns_none_when_no_model_is_trained(self):
        df = pd.DataFrame({"demand_mw": [8000], "price_mwh": [60]})

        assert ml_anomaly.score(df, "aemo_nem") is None

    def test_flags_a_clear_multivariate_outlier(self):
        _clustered_history(ml_anomaly.MIN_TRAINING_ROWS + 20)
        model = ml_anomaly.train("aemo_nem", "aemo_nem_dispatch")
        assert model is not None
        ml_anomaly.save_local(model)
        ml_anomaly.invalidate_cache("aemo_nem")

        df = pd.DataFrame(
            {
                "demand_mw": [
                    8010,
                    19000,
                ],  # second row: wildly outside the trained cluster
                "price_mwh": [61, -900],
            }
        )

        scores = ml_anomaly.score(df, "aemo_nem")

        assert scores is not None
        assert scores.iloc[1] > scores.iloc[0]
        assert scores.iloc[1] >= ml_anomaly.ANOMALY_SCORE_THRESHOLD

    def test_does_not_flag_plausible_values_from_a_widely_spread_history(self):
        """Regression test for a real miscalibration bug found live
        2026-08-05: an earlier version scored `score_samples` directly
        against a fixed assumed range, which worked on tightly-clustered
        synthetic test data (`_clustered_history`'s `normal(8000, 50)`)
        but flagged *almost every row, including plausible ones* against
        real AEMO-NEM history's actual, much wider natural spread. This
        uses a deliberately wide/varied training distribution (closer to
        real multi-region demand data) to catch that class of bug again.
        """
        rng = np.random.default_rng(1)
        wide_history = pd.DataFrame(
            {
                "demand_mw": rng.uniform(
                    500, 11000, ml_anomaly.MIN_TRAINING_ROWS + 200
                ),
                "price_mwh": rng.uniform(-60, 175, ml_anomaly.MIN_TRAINING_ROWS + 200),
            }
        )
        stage_dataframe(wide_history, "aemo_nem_dispatch", "wide-history-run")

        model = ml_anomaly.train("aemo_nem", "aemo_nem_dispatch")
        assert model is not None
        ml_anomaly.save_local(model)
        ml_anomaly.invalidate_cache("aemo_nem")

        plausible = pd.DataFrame(
            {"demand_mw": [8200, 4500, 1200], "price_mwh": [55, 40, 10]}
        )
        scores = ml_anomaly.score(plausible, "aemo_nem")

        assert scores is not None
        assert (scores < ml_anomaly.ANOMALY_SCORE_THRESHOLD).all(), scores.tolist()

    def test_rows_missing_a_trained_column_score_zero_not_nan(self):
        _clustered_history(ml_anomaly.MIN_TRAINING_ROWS + 5)
        model = ml_anomaly.train("aemo_nem", "aemo_nem_dispatch")
        assert model is not None
        ml_anomaly.save_local(model)
        ml_anomaly.invalidate_cache("aemo_nem")

        df = pd.DataFrame({"demand_mw": [8000, None], "price_mwh": [60, 60]})

        scores = ml_anomaly.score(df, "aemo_nem")

        assert scores is not None
        assert scores.iloc[1] == 0.0
        assert not scores.isna().any()

    def test_caches_the_loaded_model_across_calls(self):
        _clustered_history(ml_anomaly.MIN_TRAINING_ROWS + 5)
        model = ml_anomaly.train("aemo_nem", "aemo_nem_dispatch")
        assert model is not None
        ml_anomaly.save_local(model)
        ml_anomaly.invalidate_cache("aemo_nem")

        df = pd.DataFrame({"demand_mw": [8000], "price_mwh": [60]})
        ml_anomaly.score(df, "aemo_nem")
        cached_forest = ml_anomaly._CACHE["aemo_nem"].forest

        ml_anomaly.score(df, "aemo_nem")

        assert ml_anomaly._CACHE["aemo_nem"].forest is cached_forest


class TestTrainAndPublish:
    async def test_returns_none_and_uploads_nothing_when_training_is_skipped(
        self, monkeypatch
    ):
        upload_file = AsyncMock()
        monkeypatch.setattr(object_storage, "upload_file", upload_file)

        result = await ml_anomaly.train_and_publish("aemo_nem", "aemo_nem_dispatch")

        assert result is None
        upload_file.assert_not_awaited()

    async def test_trains_saves_uploads_and_invalidates_the_cache(self, monkeypatch):
        n = ml_anomaly.MIN_TRAINING_ROWS + 10
        _clustered_history(n)

        upload_file = AsyncMock(
            return_value="s3://ecolens/models/anomaly/aemo_nem.joblib"
        )
        monkeypatch.setattr(object_storage, "upload_file", upload_file)

        # Prime the cache with a stale `None` first, same as a real
        # process that scored this source before any model existed.
        assert ml_anomaly.score(pd.DataFrame({"demand_mw": [1]}), "aemo_nem") is None

        result = await ml_anomaly.train_and_publish("aemo_nem", "aemo_nem_dispatch")

        assert result == {
            "source": "aemo_nem",
            "rows_trained": n,
            "columns": ["demand_mw", "price_mwh"],
            "object_storage_key": "models/anomaly/aemo_nem.joblib",
        }
        upload_file.assert_awaited_once()
        call_path, call_key = upload_file.call_args.args
        assert call_key == "models/anomaly/aemo_nem.joblib"
        assert call_path.exists()
        # The stale cached `None` must be gone -- the very next score()
        # call should pick up the freshly trained/saved model.
        assert "aemo_nem" not in ml_anomaly._CACHE
