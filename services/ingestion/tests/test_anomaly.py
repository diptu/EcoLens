import json
from contextlib import asynccontextmanager

import pandas as pd
import pytest

from app.core.config import get_settings
from app.service.pipeline import anomaly, ml_anomaly

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate_ml_anomaly_state(tmp_path, monkeypatch):
    """`detect_anomalies` calls the real `ml_anomaly.score` (unless a
    test monkeypatches it, like `TestMLSignal` mostly does) -- without
    this, its disk lookups/in-process model cache would reach the real
    local `duckdb_staging_dir` and could pick up an actually-trained
    model left over from real CLI use, making these tests' outcomes
    depend on unrelated local machine state. Same `DUCKDB_STAGING_DIR`
    override `test_duckdb_staging.py`/`test_ml_anomaly.py` use, plus a
    cache reset (`ml_anomaly._CACHE` is a module-global dict, otherwise
    a model cached by an earlier test/file would leak into this one)."""
    monkeypatch.setenv("DUCKDB_STAGING_DIR", str(tmp_path))
    get_settings.cache_clear()
    ml_anomaly.invalidate_cache()
    yield
    ml_anomaly.invalidate_cache()
    get_settings.cache_clear()


def test_out_of_range_value_is_flagged():
    df = pd.DataFrame({"demand_mw": [8000, 8100, -50, 8200]})

    result = anomaly.detect_anomalies(df, "aemo_nem")

    assert len(result) == 1
    assert result.iloc[0]["demand_mw"] == -50
    assert "out_of_range:demand_mw" in result.iloc[0]["anomaly_reason"]
    assert result.iloc[0]["anomaly_score"] == 1.0
    assert result.iloc[0]["anomaly_metric"] == "demand_mw"
    assert result.iloc[0]["anomaly_value"] == -50.0
    assert result.iloc[0]["anomaly_expected_low"] == 0.0
    assert result.iloc[0]["anomaly_expected_high"] == 20000.0
    assert result.iloc[0]["anomaly_z_score"] is None


def test_missing_value_is_flagged():
    df = pd.DataFrame({"demand_mw": [8000, 8100, None, 8200]})

    result = anomaly.detect_anomalies(df, "aemo_nem")

    assert len(result) == 1
    assert "missing_value:demand_mw" in result.iloc[0]["anomaly_reason"]
    assert result.iloc[0]["anomaly_score"] == 0.5
    assert result.iloc[0]["anomaly_metric"] == "demand_mw"
    assert result.iloc[0]["anomaly_value"] is None


def test_statistical_outlier_is_flagged():
    # 9 values tightly clustered around 8000, one wild outlier.
    values = [8000, 8010, 7990, 8005, 7995, 8000, 8010, 7990, 8000, 50000]
    df = pd.DataFrame({"demand_mw": values})

    result = anomaly.detect_anomalies(df, "aemo_nem")

    reasons = " ".join(result["anomaly_reason"])
    assert "50000" in str(result["demand_mw"].tolist())
    assert "out_of_range" in reasons or "statistical_outlier" in reasons


def test_statistical_outlier_within_bounds_captures_z_score():
    # In-bounds (0-20000) but a clear statistical outlier against the
    # rest of the batch -- isolates the z-score path from out_of_range,
    # since both can trigger together on a wild-enough value. Needs a
    # reasonably-sized, mildly-varied background (not all-identical --
    # with n identical points + 1 outlier, the outlier's own self-included
    # z-score is mathematically bounded by sqrt(n-1) as the outlier's
    # value grows without limit, e.g. it can never exceed 3.0 for n=10) to
    # actually clear the z>3 threshold.
    background = [
        7980,
        8010,
        7995,
        8005,
        8000,
        7990,
        8015,
        7985,
        8000,
        8008,
        7992,
        8003,
        7998,
        8012,
        7988,
        8001,
        7999,
        8006,
        7994,
        8000,
    ]
    values = background + [15000]
    df = pd.DataFrame({"demand_mw": values})

    result = anomaly.detect_anomalies(df, "aemo_nem")

    assert len(result) == 1
    row = result.iloc[0]
    assert row["demand_mw"] == 15000
    assert "statistical_outlier:demand_mw" in row["anomaly_reason"]
    assert row["anomaly_metric"] == "demand_mw"
    assert row["anomaly_value"] == 15000.0
    assert row["anomaly_z_score"] > 3.0
    assert row["anomaly_expected_low"] is not None
    assert row["anomaly_expected_high"] is not None


def test_plausible_values_are_not_flagged():
    df = pd.DataFrame(
        {"demand_mw": [8000, 8100, 8050, 8200, 8150], "price_mwh": [50, 55, 48, 60, 52]}
    )

    result = anomaly.detect_anomalies(df, "aemo_nem")

    assert result.empty


def test_empty_dataframe_returns_empty_result():
    df = pd.DataFrame({"demand_mw": []})

    result = anomaly.detect_anomalies(df, "aemo_nem")

    assert result.empty
    assert "anomaly_score" in result.columns
    assert "anomaly_reason" in result.columns


def test_source_with_no_configured_columns_is_never_flagged():
    df = pd.DataFrame(
        {"date": ["2026-01-01"], "region": ["NSW1"], "is_workday": [True]}
    )

    result = anomaly.detect_anomalies(df, "aemo_holidays")

    assert result.empty


def test_unknown_source_is_never_flagged():
    df = pd.DataFrame({"demand_mw": [-999999]})

    result = anomaly.detect_anomalies(df, "some_unregistered_source")

    assert result.empty


def test_only_columns_present_in_the_dataframe_are_scanned():
    # bom's configured columns include wind_speed_kmh, but this fetch
    # doesn't have that column -- shouldn't KeyError.
    df = pd.DataFrame({"temp_c": [20, 21, 1000]})

    result = anomaly.detect_anomalies(df, "bom")

    assert len(result) == 1
    assert result.iloc[0]["temp_c"] == 1000


class TestMLSignal:
    """`detect_anomalies`' third signal (`pipeline.ml_anomaly.score`) --
    monkeypatched directly rather than training a real model here, since
    `test_ml_anomaly.py` already covers `ml_anomaly` itself; this class
    only checks the *integration* (combined correctly via `_Winner`,
    `None` leaves existing rule/z-score-only behaviour untouched)."""

    def test_none_from_ml_anomaly_leaves_behaviour_unchanged(self, monkeypatch):
        # The real, expected default state (no model trained yet) --
        # every other test in this file already exercises this
        # implicitly; this just makes the contract explicit.
        monkeypatch.setattr(ml_anomaly, "score", lambda df, source: None)
        df = pd.DataFrame({"demand_mw": [8000, 8100, 8050]})

        result = anomaly.detect_anomalies(df, "aemo_nem")

        assert result.empty

    def test_a_high_ml_score_flags_a_row_the_other_signals_missed(self, monkeypatch):
        df = pd.DataFrame({"demand_mw": [8000, 8100, 8050]})
        monkeypatch.setattr(
            ml_anomaly,
            "score",
            lambda df, source: pd.Series([0.1, 0.9, 0.2], index=df.index),
        )

        result = anomaly.detect_anomalies(df, "aemo_nem")

        assert len(result) == 1
        assert result.iloc[0]["demand_mw"] == 8100
        assert "ml_outlier:isolation_forest" in result.iloc[0]["anomaly_reason"]
        assert result.iloc[0]["anomaly_metric"] == "ml_isolation_forest"
        assert result.iloc[0]["anomaly_score"] == pytest.approx(0.9)
        assert result.iloc[0]["anomaly_value"] is None

    def test_ml_score_below_threshold_does_not_flag(self, monkeypatch):
        df = pd.DataFrame({"demand_mw": [8000, 8100]})
        monkeypatch.setattr(
            ml_anomaly,
            "score",
            lambda df, source: pd.Series(
                [0.1, ml_anomaly.ANOMALY_SCORE_THRESHOLD - 0.01], index=df.index
            ),
        )

        result = anomaly.detect_anomalies(df, "aemo_nem")

        assert result.empty

    def test_the_worse_of_ml_and_rule_based_wins(self, monkeypatch):
        # out_of_range always scores 1.0 -- higher than any ML score --
        # so the rule-based signal should still win the `_Winner` combine
        # even with a real ML signal present.
        df = pd.DataFrame({"demand_mw": [-50]})
        monkeypatch.setattr(
            ml_anomaly, "score", lambda df, source: pd.Series([0.9], index=df.index)
        )

        result = anomaly.detect_anomalies(df, "aemo_nem")

        assert len(result) == 1
        assert result.iloc[0]["anomaly_metric"] == "demand_mw"
        assert "out_of_range:demand_mw" in result.iloc[0]["anomaly_reason"]
        assert "ml_outlier" in result.iloc[0]["anomaly_reason"]
        assert result.iloc[0]["anomaly_score"] == 1.0

    def test_ml_wins_over_a_smaller_rule_based_score(self, monkeypatch):
        # missing_value always scores 0.5 -- a high-enough ML score
        # should win the combine instead.
        df = pd.DataFrame({"demand_mw": [None]})
        monkeypatch.setattr(
            ml_anomaly, "score", lambda df, source: pd.Series([0.95], index=df.index)
        )

        result = anomaly.detect_anomalies(df, "aemo_nem")

        assert len(result) == 1
        assert result.iloc[0]["anomaly_metric"] == "ml_isolation_forest"
        assert result.iloc[0]["anomaly_score"] == pytest.approx(0.95)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows


class _FakeSession:
    def __init__(self):
        self.executed: list[tuple[str, object]] = []

    async def execute(self, query, params=None):
        self.executed.append((str(query), params))
        if isinstance(params, list):
            return _FakeResult(None)
        return _FakeResult([3])


async def test_record_anomalies_is_a_noop_for_an_empty_frame(monkeypatch):
    session = _FakeSession()

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(anomaly, "get_session", fake_get_session)

    empty = pd.DataFrame({"anomaly_score": [], "anomaly_reason": []})
    await anomaly.record_anomalies("run-1", "aemo_nem", "aemo_nem_dispatch", empty)

    assert session.executed == []


async def test_record_anomalies_inserts_one_row_per_flagged_record(monkeypatch):
    session = _FakeSession()

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(anomaly, "get_session", fake_get_session)

    # Real detect_anomalies() output, not a hand-built stand-in -- keeps
    # this test honest about the actual shape record_anomalies receives
    # (all of _RESULT_COLUMNS, not just anomaly_score/anomaly_reason).
    df = pd.DataFrame({"demand_mw": [-50, 99999]})
    flagged = anomaly.detect_anomalies(df, "aemo_nem")

    await anomaly.record_anomalies("run-1", "aemo_nem", "aemo_nem_dispatch", flagged)

    assert len(session.executed) == 1
    query, params = session.executed[0]
    assert "INSERT INTO meta.anomalies" in query
    assert len(params) == 2
    assert params[0]["source"] == "aemo_nem"
    assert params[0]["table_name"] == "aemo_nem_dispatch"
    assert params[0]["metric"] == "demand_mw"
    assert params[0]["value"] == -50.0
    assert params[0]["expected_low"] == 0.0
    assert params[0]["expected_high"] == 20000.0
    assert params[0]["z_score"] is None
    assert "demand_mw" in params[0]["row_snapshot"]


async def test_record_anomalies_produces_valid_json_for_a_nan_snapshot_value(
    monkeypatch,
):
    """Regression: `aemo_wem`'s `price_mwh` is a real, honest NaN on
    5-min-only rows (5/6 of its data) -- `demand_mw` missing/out-of-range
    is a comparatively rare flag, but a NaN `price_mwh` gets flagged as
    `missing_value:price_mwh` on nearly every WEM row, every WEM ingest.
    Before `_json_safe_snapshot`, `json.dumps` on a dict containing a
    float NaN produced the bare (invalid-JSON) `NaN` token, which
    Postgres's `jsonb` parser rejected -- silently failing *every* WEM
    backfill day at the `record_anomalies` step, even though the fetch
    itself succeeded."""
    session = _FakeSession()

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(anomaly, "get_session", fake_get_session)

    df = pd.DataFrame(
        {"demand_mw": [2500.0, 2490.0], "price_mwh": [95.83, float("nan")]}
    )
    flagged = anomaly.detect_anomalies(df, "aemo_wem")
    assert len(flagged) == 1  # only the NaN-price row is flagged here

    await anomaly.record_anomalies("run-1", "aemo_wem", "aemo_wem_dispatch", flagged)

    _, params = session.executed[0]
    snapshot_json = params[0]["row_snapshot"]
    # The actual Postgres failure mode: `jsonb`'s strict-JSON parser
    # rejects a bare `NaN` token outright, unlike Python's own `json`
    # module which happily reads it back as `float("nan")` -- so the real
    # regression check is the token's absence here, not just that
    # `json.loads` (Python-lenient) can parse the string.
    assert "NaN" not in snapshot_json
    parsed = json.loads(snapshot_json)
    assert parsed["price_mwh"] is None
    assert parsed["demand_mw"] == 2490.0


async def test_count_anomalies_returns_the_query_result(monkeypatch):
    session = _FakeSession()

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(anomaly, "get_session", fake_get_session)

    count = await anomaly.count_anomalies("run-1")

    assert count == 3
