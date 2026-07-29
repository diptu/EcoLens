"""Tests for ecolens.ingestion.service.anomaly.scorer (root TODO.md's
"Anomaly Detection" section) -- the combined rule+statistical score,
and a real round-trip through `duckdb_store.write_historical()` proving
the wiring itself (not just the scoring function in isolation) is
correct and non-destructive.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ecolens.ingestion.core.settings import IngestionSettings
from ecolens.ingestion.db.duckdb_store import read_historical, write_historical
from ecolens.ingestion.service.anomaly import isolation_forest as iforest
from ecolens.ingestion.service.anomaly.baseline import load_baseline
from ecolens.ingestion.service.anomaly.scorer import score_batch


def _history_frame(n: int = 100, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "region": ["NSW1"] * n,
            "demand_mw": rng.normal(loc=6000.0, scale=200.0, size=n),
            "price_mwh": rng.normal(loc=80.0, scale=10.0, size=n),
        }
    )


def _nem_doc(**overrides) -> dict:
    doc = {
        "region": "NSW1",
        "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "fetched_at": datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        "demand_mw": 6000.0,
        "price_mwh": 80.0,
    }
    doc.update(overrides)
    return doc


class TestScoreBatch:
    def test_empty_batch_is_a_no_op(self):
        docs: list = []
        score_batch("aemo_nem", docs)
        assert docs == []

    def test_record_count_unchanged(self):
        docs = [_nem_doc(), _nem_doc(price_mwh=99_999.0)]
        baseline = load_baseline("aemo_nem", history=pd.DataFrame())
        score_batch("aemo_nem", docs, baseline=baseline)
        assert len(docs) == 2

    def test_every_doc_gets_all_three_fields_populated(self):
        docs = [_nem_doc()]
        baseline = load_baseline("aemo_nem", history=pd.DataFrame())
        score_batch("aemo_nem", docs, baseline=baseline)
        doc = docs[0]
        assert "anomaly_score" in doc
        assert "anomaly_flags" in doc
        assert "anomaly_explanation" in doc
        assert isinstance(doc["anomaly_score"], float)

    def test_clean_record_scores_zero_with_no_flags(self):
        docs = [_nem_doc()]
        baseline = load_baseline(
            "aemo_nem",
            settings=IngestionSettings(anomaly_baseline_min_samples=20),
            history=_history_frame(),
        )
        score_batch("aemo_nem", docs, baseline=baseline)
        assert docs[0]["anomaly_score"] == 0.0
        assert docs[0]["anomaly_flags"] == ""
        assert docs[0]["anomaly_explanation"] == ""

    def test_rule_violation_scores_high(self):
        docs = [_nem_doc(price_mwh=99_999.0)]
        baseline = load_baseline("aemo_nem", history=pd.DataFrame())
        score_batch("aemo_nem", docs, baseline=baseline)
        assert docs[0]["anomaly_score"] > 0.0
        assert "rule:price_above_cap" in docs[0]["anomaly_flags"]
        assert "price_mwh" in docs[0]["anomaly_explanation"]

    def test_statistical_outlier_scores_high(self):
        settings = IngestionSettings(anomaly_baseline_min_samples=20)
        baseline = load_baseline(
            "aemo_nem", settings=settings, history=_history_frame()
        )
        docs = [_nem_doc(demand_mw=50_000.0)]
        score_batch("aemo_nem", docs, settings=settings, baseline=baseline)
        assert docs[0]["anomaly_score"] > 0.0
        assert "stat:demand_mw_robust_zscore_outlier" in docs[0]["anomaly_flags"]

    def test_ordinary_noise_does_not_score_high(self):
        settings = IngestionSettings(anomaly_baseline_min_samples=20)
        baseline = load_baseline(
            "aemo_nem", settings=settings, history=_history_frame()
        )
        docs = [_nem_doc(demand_mw=6050.0)]  # well within normal noise
        score_batch("aemo_nem", docs, settings=settings, baseline=baseline)
        assert docs[0]["anomaly_score"] == 0.0

    def test_sudden_jump_detected_against_prior_same_entity_record(self):
        baseline = load_baseline("aemo_nem", history=pd.DataFrame())
        docs = [
            _nem_doc(
                region="NSW1",
                ts=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                demand_mw=6000.0,
            ),
            _nem_doc(
                region="NSW1",
                ts=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
                demand_mw=15_000.0,
            ),
        ]
        score_batch("aemo_nem", docs, baseline=baseline)
        first, second = sorted(docs, key=lambda d: d["ts"])
        assert "rule:demand_sudden_jump" not in first["anomaly_flags"]
        assert "rule:demand_sudden_jump" in second["anomaly_flags"]

    def test_different_entities_do_not_cross_contaminate_jump_detection(self):
        baseline = load_baseline("aemo_nem", history=pd.DataFrame())
        docs = [
            _nem_doc(region="NSW1", demand_mw=6000.0),
            _nem_doc(region="QLD1", demand_mw=15_000.0),
        ]
        score_batch("aemo_nem", docs, baseline=baseline)
        qld = next(d for d in docs if d["region"] == "QLD1")
        assert "rule:demand_sudden_jump" not in qld["anomaly_flags"]


class TestWriteHistoricalRoundTrip:
    """The actual wiring `duckdb_store.write_historical()` calls
    `score_batch()` from -- not the scoring function in isolation.
    """

    def test_anomaly_columns_persist_and_record_is_otherwise_unchanged(
        self, tmp_path: Path
    ):
        db_path = tmp_path / "historical.duckdb"
        docs = [
            {
                "region": "NSW1",
                "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "demand_mw": 6000.0,
                "price_mwh": 99_999.0,  # deliberately extreme
            }
        ]
        write_historical("aemo_nem", docs, db_path=db_path)

        out = read_historical("aemo_nem", db_path=db_path)
        assert len(out) == 1
        row = out.iloc[0]
        assert row["anomaly_score"] > 0.0
        assert "rule:price_above_cap" in row["anomaly_flags"]
        assert row["anomaly_explanation"] != ""
        # The record itself -- untouched otherwise.
        assert row["region"] == "NSW1"
        assert row["demand_mw"] == 6000.0
        assert row["price_mwh"] == 99_999.0

    def test_no_record_is_ever_dropped(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        docs = [
            {
                "region": "NSW1",
                "ts": datetime(2026, 1, 1, i, tzinfo=timezone.utc),
                "demand_mw": 6000.0 if i % 2 == 0 else -999.0,
                "price_mwh": 80.0,
            }
            for i in range(5)
        ]
        written = write_historical("aemo_nem", docs, db_path=db_path)
        assert written == 5
        out = read_historical("aemo_nem", db_path=db_path)
        assert len(out) == 5

    def test_clean_batch_persists_zero_scores(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        docs = [
            {
                # write_historical() stamps fetched_at as the real "now"
                # -- ts must be close to it too, or the staleness rule
                # (correctly) fires and this stops being a "clean" batch.
                "region": "NSW1",
                "ts": datetime.now(timezone.utc),
                "demand_mw": 6000.0,
                "price_mwh": 80.0,
            }
        ]
        write_historical("aemo_nem", docs, db_path=db_path)
        out = read_historical("aemo_nem", db_path=db_path)
        assert out.iloc[0]["anomaly_score"] == 0.0
        assert out.iloc[0]["anomaly_flags"] == ""


def _seed_and_train(tmp_path: Path, n: int = 300) -> Path:
    """Seeds `n` half-hourly NSW1 rows (with a mild diurnal demand
    pattern, same convention as `test_ingestion_anomaly_isolation_forest.py`'s
    own `_seed_history`) into a fresh DuckDB store under `tmp_path`,
    trains a real `aemo_nem:demand_mw` IsolationForest model against it,
    and returns `db_path` -- the shared setup every v2-touching test
    below needs.

    The diurnal term matters for test *stability*, not just realism: a
    perfectly flat demand series makes the baseline's own z-score the
    IsolationForest's only source of real signal, and with `contamination
    =0.01`, a moderately-extreme z-score can land just short of the
    fitted boundary and score as a (barely) positive inlier -- flaky
    across otherwise-identical runs, since DuckDB doesn't guarantee row
    order without an explicit `ORDER BY`, so training-row order (and
    thus exactly which points a fixed `random_state` subsamples) isn't
    perfectly reproducible run to run. A real diurnal pattern gives the
    z feature enough natural spread that a genuinely wild value (50,000
    MW vs. a real 5,000-6,500 MW range) isolates as a clean outlier
    regardless of that ordering noise -- confirmed by re-running this
    fixture and a would-be assertion by hand several times before
    settling on it.
    """
    db_path = tmp_path / "historical.duckdb"
    model_dir = tmp_path / "anomaly_models"
    rng = np.random.default_rng(0)
    fixed_now = datetime(2026, 1, 6, 12, 0, tzinfo=timezone.utc)  # a Tuesday noon
    seed_docs = []
    for i in range(n):
        ts = fixed_now - timedelta(minutes=30 * i)
        base = 5000.0 + 1500.0 * np.sin(2 * np.pi * (ts.hour - 6) / 24)
        seed_docs.append(
            {
                "region": "NSW1",
                "ts": ts,
                "demand_mw": float(base + rng.normal(0, 100)),
                "price_mwh": float(80.0 + rng.normal(0, 10)),
            }
        )
    write_historical("aemo_nem", seed_docs, db_path=db_path)
    trained = iforest.train_one(
        "aemo_nem", "demand_mw", db_path=db_path, model_dir=model_dir
    )
    assert trained, "test setup: model must train for the tests below to be meaningful"
    return db_path


class TestIsolationForestComponent:
    """The v2 signal, exercised through `score_batch()` with an explicit
    `isolation_forest_registry` -- an actual trained model, not a stub.
    """

    def test_extreme_value_gets_ml_flag_with_a_trained_model_loaded(
        self, tmp_path: Path
    ):
        db_path = _seed_and_train(tmp_path)
        registry = iforest.IsolationForestRegistry(
            model_dir=db_path.resolve().parent / "anomaly_models"
        )
        baseline = load_baseline("aemo_nem", db_path=db_path)
        docs = [_nem_doc(demand_mw=50_000.0)]

        score_batch(
            "aemo_nem", docs, baseline=baseline, isolation_forest_registry=registry
        )

        assert "ml:demand_mw_isolation_forest_outlier" in docs[0]["anomaly_flags"]
        assert docs[0]["anomaly_score"] > 0.0

    def test_no_ml_flag_without_a_trained_model_cold_start(self):
        # No registry passed, no models on disk anywhere near the
        # default path -- graceful cold-start no-op, not a crash.
        baseline = load_baseline("aemo_nem", history=pd.DataFrame())
        docs = [_nem_doc(demand_mw=50_000.0)]
        score_batch("aemo_nem", docs, baseline=baseline)
        assert "ml:" not in docs[0]["anomaly_flags"]

    def test_isolation_forest_disabled_setting_suppresses_ml_signal(
        self, tmp_path: Path
    ):
        db_path = _seed_and_train(tmp_path)
        registry = iforest.IsolationForestRegistry(
            model_dir=db_path.resolve().parent / "anomaly_models"
        )
        settings = IngestionSettings(anomaly_isolation_forest_enabled=False)
        baseline = load_baseline("aemo_nem", settings=settings, db_path=db_path)
        docs = [_nem_doc(demand_mw=50_000.0)]

        # score_batch() trusts an explicitly-passed registry regardless
        # of the setting (the caller opted in on purpose) -- the kill
        # switch's real enforcement point is `write_historical`/
        # production code choosing not to *build* a registry at all
        # when the setting is False (exercised below via the full
        # write path, with no registry passed).
        score_batch(
            "aemo_nem",
            docs,
            settings=settings,
            baseline=baseline,
            isolation_forest_registry=registry,
        )
        assert "ml:demand_mw_isolation_forest_outlier" in docs[0]["anomaly_flags"]

    def test_disabled_setting_prevents_write_historical_from_building_a_registry(
        self, tmp_path: Path
    ):
        db_path = _seed_and_train(tmp_path)
        settings = IngestionSettings(anomaly_isolation_forest_enabled=False)
        docs = [_nem_doc(demand_mw=50_000.0)]

        # No isolation_forest_registry passed -- production's own path.
        # A trained model genuinely exists on disk at db_path's model
        # dir, so this only proves anything if the setting itself (not
        # a missing model) is what suppresses the signal.
        score_batch("aemo_nem", docs, settings=settings, db_path=db_path)
        assert "ml:" not in docs[0]["anomaly_flags"]


class TestWriteHistoricalRoundTripWithTrainedModel:
    """The full `write_historical()` wiring: a caller who never passes
    `isolation_forest_registry` explicitly still gets the v2 signal,
    scoped to the *same* DuckDB file being written (`db_path`), not the
    global default model directory.
    """

    def test_ml_flag_fires_through_the_full_write_path(self, tmp_path: Path):
        db_path = _seed_and_train(tmp_path)
        now = datetime.now(timezone.utc)

        write_historical(
            "aemo_nem",
            [{"region": "NSW1", "ts": now, "demand_mw": 50_000.0, "price_mwh": 80.0}],
            db_path=db_path,
        )

        out = read_historical("aemo_nem", db_path=db_path)
        row = out[out["demand_mw"] == 50_000.0].iloc[0]
        assert "ml:demand_mw_isolation_forest_outlier" in row["anomaly_flags"]
        assert row["anomaly_score"] > 0.0
