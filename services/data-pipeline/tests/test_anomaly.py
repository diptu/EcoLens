from contextlib import asynccontextmanager

import pandas as pd
import pytest

from app.service.pipeline import anomaly

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


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


async def test_count_anomalies_returns_the_query_result(monkeypatch):
    session = _FakeSession()

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(anomaly, "get_session", fake_get_session)

    count = await anomaly.count_anomalies("run-1")

    assert count == 3
