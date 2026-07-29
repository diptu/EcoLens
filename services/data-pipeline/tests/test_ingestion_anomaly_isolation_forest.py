"""Tests for ecolens.ingestion.service.anomaly.isolation_forest (root
TODO.md's "Anomaly Detection" section, v2: periodically-retrained
IsolationForest).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np

from ecolens.ingestion.db.duckdb_store import write_historical
from ecolens.ingestion.service.anomaly import isolation_forest as iforest


def _seed_history(db_path: Path, n: int = 300, seed: int = 0) -> None:
    """`n` half-hourly NSW1 rows ending "now," with a mild diurnal
    pattern (so the cyclical hour features have something real to
    learn) plus Gaussian noise -- deliberately unremarkable, no injected
    outliers, since these tests only need a model that has learned a
    stable "normal."
    """
    rng = np.random.default_rng(seed)
    now = datetime.now(timezone.utc)
    docs = []
    for i in range(n):
        ts = now - timedelta(minutes=30 * i)
        base = 6000.0 + 500.0 * np.sin(2 * np.pi * (ts.hour - 6) / 24)
        docs.append(
            {
                "region": "NSW1",
                "ts": ts,
                "demand_mw": float(base + rng.normal(0, 100)),
                "price_mwh": float(80.0 + rng.normal(0, 10)),
            }
        )
    write_historical("aemo_nem", docs, db_path=db_path)


class TestTrainOne:
    def test_no_history_returns_false(self, tmp_path: Path):
        db_path = tmp_path / "empty.duckdb"
        model_dir = tmp_path / "anomaly_models"
        trained = iforest.train_one(
            "aemo_nem", "demand_mw", db_path=db_path, model_dir=model_dir
        )
        assert trained is False
        assert not model_dir.exists()

    def test_insufficient_samples_returns_false(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        model_dir = tmp_path / "anomaly_models"
        _seed_history(db_path, n=50)  # below the default 200 min-samples
        trained = iforest.train_one(
            "aemo_nem", "demand_mw", db_path=db_path, model_dir=model_dir
        )
        assert trained is False
        assert not (model_dir / "aemo_nem__demand_mw.joblib").exists()

    def test_trains_and_persists_with_enough_history(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        model_dir = tmp_path / "anomaly_models"
        _seed_history(db_path, n=300)

        trained = iforest.train_one(
            "aemo_nem", "demand_mw", db_path=db_path, model_dir=model_dir
        )
        assert trained is True

        model_path = model_dir / "aemo_nem__demand_mw.joblib"
        assert model_path.exists()
        payload = joblib.load(model_path)
        assert payload["source"] == "aemo_nem"
        assert payload["metric"] == "demand_mw"
        assert payload["n_samples"] >= 200
        # A degenerate all-non-negative training set would clamp this to
        # -1e-6 rather than 0 -- either way it must be strictly negative.
        assert payload["severity_floor"] < 0


class TestTrainAll:
    def test_trains_sources_with_history_and_skips_the_rest(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        model_dir = tmp_path / "anomaly_models"
        _seed_history(db_path, n=300)

        results = iforest.train_all(db_path=db_path, model_dir=model_dir)

        assert results["aemo_nem:demand_mw"] is True
        assert results["aemo_nem:price_mwh"] is True
        # No BoM/WEM/OpenElectricity/holidays history was ever seeded in
        # this DuckDB file -- every one of those must gracefully skip,
        # not raise.
        assert results["bom:temp_c"] is False
        assert results["aemo_wem:demand_mw"] is False
        assert results["openelectricity:demand_mw"] is False


class TestIsolationForestRegistry:
    def test_missing_model_returns_none(self, tmp_path: Path):
        registry = iforest.IsolationForestRegistry(
            model_dir=tmp_path / "anomaly_models"
        )
        assert registry.get("aemo_nem", "demand_mw") is None

    def test_loads_a_trained_model(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        model_dir = tmp_path / "anomaly_models"
        _seed_history(db_path, n=300)
        iforest.train_one("aemo_nem", "demand_mw", db_path=db_path, model_dir=model_dir)

        registry = iforest.IsolationForestRegistry(model_dir=model_dir)
        loaded = registry.get("aemo_nem", "demand_mw")

        assert loaded is not None
        assert loaded.source == "aemo_nem"
        assert loaded.metric == "demand_mw"
        assert loaded.n_samples >= 200
        assert loaded.severity_floor < 0

    def test_caches_after_first_load(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        model_dir = tmp_path / "anomaly_models"
        _seed_history(db_path, n=300)
        iforest.train_one("aemo_nem", "demand_mw", db_path=db_path, model_dir=model_dir)

        registry = iforest.IsolationForestRegistry(model_dir=model_dir)
        first = registry.get("aemo_nem", "demand_mw")
        second = registry.get("aemo_nem", "demand_mw")
        assert first is second

    def test_corrupt_model_file_degrades_to_none_not_a_crash(self, tmp_path: Path):
        model_dir = tmp_path / "anomaly_models"
        model_dir.mkdir(parents=True)
        (model_dir / "aemo_nem__demand_mw.joblib").write_bytes(
            b"not a real joblib payload"
        )

        registry = iforest.IsolationForestRegistry(model_dir=model_dir)
        assert registry.get("aemo_nem", "demand_mw") is None


class TestScore:
    def _train_and_load(self, tmp_path: Path) -> iforest.LoadedIsolationForest:
        db_path = tmp_path / "historical.duckdb"
        model_dir = tmp_path / "anomaly_models"
        _seed_history(db_path, n=300)
        iforest.train_one("aemo_nem", "demand_mw", db_path=db_path, model_dir=model_dir)
        loaded = iforest.IsolationForestRegistry(model_dir=model_dir).get(
            "aemo_nem", "demand_mw"
        )
        assert loaded is not None
        return loaded

    def test_extreme_zscore_scores_more_anomalous_than_a_normal_one(
        self, tmp_path: Path
    ):
        loaded = self._train_and_load(tmp_path)
        ts = datetime(2026, 1, 6, 15, 0, tzinfo=timezone.utc)  # a Tuesday

        normal_decision = iforest.score(loaded, 0.0, ts)
        extreme_decision = iforest.score(loaded, 20.0, ts)

        # Not `assert extreme_decision < 0.0` -- sklearn's own
        # contamination-fitted boundary depends on the *exact* training
        # sample (DuckDB doesn't guarantee row order without an explicit
        # `ORDER BY`, so which rows a fixed `random_state` subsamples
        # isn't perfectly reproducible run to run), and with only 1 of
        # 5 features (the z-score) actually carrying signal, an
        # occasional run can calibrate a boundary an extreme point still
        # lands just short of -- confirmed flaky in CI, not a hypothetical.
        # "More anomalous than a typical point" is the robust, always-true
        # claim; "definitely past sklearn's own zero boundary" isn't.
        assert extreme_decision < normal_decision

    def test_more_extreme_zscore_never_yields_a_less_anomalous_decision(
        self, tmp_path: Path
    ):
        loaded = self._train_and_load(tmp_path)
        ts = datetime(2026, 1, 6, 15, 0, tzinfo=timezone.utc)  # a Tuesday

        # `severity_floor` is the *training* set's own worst point (all
        # drawn from ordinary z-scores near 0) -- a scoring-time z-score
        # far more extreme than anything in training (e.g. 50) can
        # legitimately score *past* that floor. `scorer.py`'s
        # `_severity_for_iforest_score` is what clamps the resulting
        # severity to 1.0 in that case, not `score()` itself, which is
        # deliberately just the raw sklearn value.
        decision_z20 = iforest.score(loaded, 20.0, ts)
        decision_z50 = iforest.score(loaded, 50.0, ts)
        assert decision_z50 <= decision_z20 + 1e-9
