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


def test_missing_value_is_not_flagged():
    """Real behavior change, 2026-08-12: the rule-based signal (out-of-
    range bounds, missing-value flagging) is retired -- see `pipeline.
    anomaly`'s own module docstring for why. A NaN value on its own no
    longer trips anything; it's silently skipped (`continue`), same as
    it would be for a column with no configured bounds at all."""
    df = pd.DataFrame({"demand_mw": [8000, 8100, None, 8200]})

    result = anomaly.detect_anomalies(df, "aemo_nem")

    assert result.empty


def test_an_extreme_out_of_range_value_is_still_caught_via_statistical_outlier():
    """Rule-based `out_of_range` is gone, but a wildly implausible value
    (negative demand) still gets caught here as long as it's also a
    statistical outlier against the rest of the batch -- this one isn't
    a guarantee (a small/uniform batch might not clear the z-score
    threshold), just confirms the statistical signal alone is enough for
    the obviously-broken case. 20-point background (not fewer), same
    reason `test_statistical_outlier_within_bounds_captures_z_score`
    below needs it: a self-included z-score is mathematically bounded by
    sqrt(n-1), so n=10 could never clear `z > 3.0` no matter how extreme
    the outlier's value."""
    background = [
        7980, 8010, 7995, 8005, 8000, 7990, 8015, 7985, 8000, 8008,
        7992, 8003, 7998, 8012, 7988, 8001, 7999, 8006, 7994, 8000,
    ]
    df = pd.DataFrame({"demand_mw": background + [-50]})

    result = anomaly.detect_anomalies(df, "aemo_nem")

    assert len(result) == 1
    assert result.iloc[0]["demand_mw"] == -50
    assert "statistical_outlier:demand_mw" in result.iloc[0]["anomaly_reason"]
    assert result.iloc[0]["anomaly_rule_based_score"] is None


def test_statistical_outlier_is_flagged():
    # A clear statistical outlier against a mildly-varied background.
    # Needs a reasonably-sized background (not all-identical, not too
    # small -- with n points + 1 outlier, the outlier's own self-included
    # z-score is mathematically bounded by sqrt(n-1) as the outlier's
    # value grows without limit, e.g. it can never exceed 3.0 for n=10)
    # to actually clear the z>3 threshold.
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
    assert row["anomaly_statistical_score"] > 0
    assert row["anomaly_rule_based_score"] is None


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
    # doesn't have that column -- shouldn't KeyError. A 20-point mildly-
    # varied background + one wild outlier (same shape/reasoning as
    # `test_statistical_outlier_is_flagged`) so the flag comes from a
    # real signal, not a since-retired rule-based bound.
    background = list(range(19, 22)) * 7  # 21 values clustered 19-21
    df = pd.DataFrame({"temp_c": background + [1000]})

    result = anomaly.detect_anomalies(df, "bom")

    assert len(result) == 1
    assert result.iloc[0]["temp_c"] == 1000


class TestMLSignal:
    """`detect_anomalies`' second signal (`pipeline.ml_anomaly.score`) --
    monkeypatched directly rather than training a real model here, since
    `test_ml_anomaly.py` already covers `ml_anomaly` itself; this class
    only checks the *integration* (combined correctly via `_Winner`,
    `None` leaves existing statistical-only behaviour untouched)."""

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
        assert result.iloc[0]["anomaly_ml_score"] == pytest.approx(0.9)
        assert result.iloc[0]["anomaly_rule_based_score"] is None
        assert result.iloc[0]["anomaly_statistical_score"] is None

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

    def test_the_worse_of_ml_and_statistical_wins(self, monkeypatch):
        # A strong statistical outlier (z=4.36, statistical_score=0.727,
        # exact values confirmed against this fixed background) should
        # win the `_Winner` combine over a real but smaller ML score.
        # Background rows get an ML score below `ANOMALY_SCORE_THRESHOLD`
        # (0.5) so only the target row's ML signal fires at all.
        background = [
            7980, 8010, 7995, 8005, 8000, 7990, 8015, 7985, 8000, 8008,
            7992, 8003, 7998, 8012, 7988, 8001, 7999, 8006, 7994, 8000,
        ]
        df = pd.DataFrame({"demand_mw": background + [15000]})
        monkeypatch.setattr(
            ml_anomaly,
            "score",
            lambda df, source: pd.Series([0.1] * (len(df) - 1) + [0.6], index=df.index),
        )

        result = anomaly.detect_anomalies(df, "aemo_nem")

        assert len(result) == 1
        row = result.iloc[0]
        assert row["demand_mw"] == 15000
        assert row["anomaly_metric"] == "demand_mw"
        # Both signals fired (ML's 0.6 clears the 0.5 threshold) -- the
        # stronger statistical score (0.727) wins the combine.
        assert "statistical_outlier:demand_mw" in row["anomaly_reason"]
        assert "ml_outlier" in row["anomaly_reason"]
        assert row["anomaly_score"] == pytest.approx(0.7274, abs=1e-3)
        assert row["anomaly_statistical_score"] == pytest.approx(0.7274, abs=1e-3)
        assert row["anomaly_ml_score"] == pytest.approx(0.6)
        assert row["anomaly_rule_based_score"] is None

    def test_ml_wins_over_a_smaller_statistical_score(self, monkeypatch):
        # A borderline statistical outlier (z=3.41, statistical_score=
        # 0.568) should lose the combine to a much higher real ML score
        # on the same row. Background rows again get a below-threshold
        # ML score so they don't get swept in as false flags.
        background = [
            7980, 8010, 7995, 8005, 8000, 7990, 8015, 7985, 8000, 8008,
            7992, 8003, 7998, 8012, 7988, 8001, 7999, 8006, 7994, 8000,
        ]
        df = pd.DataFrame({"demand_mw": background + [8050]})
        monkeypatch.setattr(
            ml_anomaly,
            "score",
            lambda df, source: pd.Series([0.1] * (len(df) - 1) + [0.95], index=df.index),
        )

        result = anomaly.detect_anomalies(df, "aemo_nem")

        assert len(result) == 1
        row = result.iloc[0]
        assert row["anomaly_metric"] == "ml_isolation_forest"
        assert "statistical_outlier:demand_mw" in row["anomaly_reason"]
        assert "ml_outlier" in row["anomaly_reason"]
        assert row["anomaly_score"] == pytest.approx(0.95)
        # Both signals fired -- the weaker statistical score (0.568) lost
        # the winner slot to ML's higher 0.95, but both are still recorded.
        assert row["anomaly_statistical_score"] == pytest.approx(0.5678, abs=1e-3)
        assert row["anomaly_ml_score"] == pytest.approx(0.95)
        assert row["anomaly_rule_based_score"] is None


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
    # 20-point background + one statistical outlier -- same fixed values
    # as `test_the_worse_of_ml_and_statistical_wins`, exact z/expected_
    # low/expected_high confirmed against this specific background.
    background = [
        7980, 8010, 7995, 8005, 8000, 7990, 8015, 7985, 8000, 8008,
        7992, 8003, 7998, 8012, 7988, 8001, 7999, 8006, 7994, 8000,
    ]
    df = pd.DataFrame({"demand_mw": background + [15000]})
    flagged = anomaly.detect_anomalies(df, "aemo_nem")

    await anomaly.record_anomalies("run-1", "aemo_nem", "aemo_nem_dispatch", flagged)

    assert len(session.executed) == 1
    query, params = session.executed[0]
    assert "INSERT INTO meta.anomalies" in query
    assert len(params) == 1
    assert params[0]["source"] == "aemo_nem"
    assert params[0]["table_name"] == "aemo_nem_dispatch"
    assert params[0]["metric"] == "demand_mw"
    assert params[0]["value"] == 15000.0
    assert params[0]["expected_low"] == pytest.approx(3749.15)
    assert params[0]["expected_high"] == pytest.approx(12915.70)
    assert params[0]["z_score"] == pytest.approx(4.36)
    assert params[0]["rule_based_score"] is None
    assert params[0]["statistical_score"] == pytest.approx(0.7274, abs=1e-3)
    assert params[0]["ml_score"] is None
    assert "demand_mw" in params[0]["row_snapshot"]
    assert "rule_based_score" not in params[0]["row_snapshot"]


async def test_record_anomalies_produces_valid_json_for_a_nan_snapshot_value(
    monkeypatch,
):
    """Regression: `aemo_wem`'s `price_mwh` is a real, honest NaN on
    5-min-only rows (5/6 of its data, AEMO only publishes price at the
    :00/:30 marks). Before `_json_safe_snapshot`, `json.dumps` on a dict
    containing a float NaN produced the bare (invalid-JSON) `NaN` token,
    which Postgres's `jsonb` parser rejected -- silently failing *every*
    WEM backfill day at the `record_anomalies` step, even though the
    fetch itself succeeded. Originally reproduced via the (now-retired)
    rule-based `missing_value:price_mwh` check flagging nearly every WEM
    row on its own; still real and still needed now that flags only come
    from the statistical/ML signals -- `row_snapshot` includes every
    column of a flagged row, not just the one that tripped the winning
    signal, so a `demand_mw` statistical outlier whose *own* row happens
    to have a NaN `price_mwh` (the normal WEM case) hits the same path."""
    session = _FakeSession()

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(anomaly, "get_session", fake_get_session)

    background_demand = [
        2480, 2510, 2495, 2505, 2500, 2490, 2515, 2485, 2500, 2508,
        2492, 2503, 2498, 2512, 2488, 2501, 2499, 2506, 2494, 2500,
    ]
    df = pd.DataFrame(
        {
            "demand_mw": background_demand + [9000],
            # Real WEM shape: price only on :00/:30 marks -- NaN
            # elsewhere, including on the flagged (outlier) row itself.
            "price_mwh": [95.83] * 20 + [float("nan")],
        }
    )
    flagged = anomaly.detect_anomalies(df, "aemo_wem")
    assert len(flagged) == 1  # only the demand_mw outlier row is flagged
    assert flagged.iloc[0]["demand_mw"] == 9000

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
    assert parsed["demand_mw"] == 9000.0


async def test_count_anomalies_returns_the_query_result(monkeypatch):
    session = _FakeSession()

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(anomaly, "get_session", fake_get_session)

    count = await anomaly.count_anomalies("run-1")

    assert count == 3
