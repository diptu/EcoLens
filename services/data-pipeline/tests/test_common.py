import uuid
from contextlib import asynccontextmanager

import pandas as pd
import pytest

from app.core.metrics import REGISTRY
from app.service.pipeline.circuit_breaker import CircuitState
from app.service.pipeline.tasks import _common

pytestmark = pytest.mark.anyio


def _ingest_runs_total(source: str, outcome: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "ecolens_ingest_runs_total", {"source": source, "outcome": outcome}
        )
        or 0.0
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _PassthroughBreaker:
    async def call(self, fn, *args, **kwargs):
        return await fn(*args, **kwargs)

    @property
    def state(self):
        return self._compute_state()

    async def _compute_state(self):
        return CircuitState.CLOSED


class _RecordingSession:
    def __init__(self, log: list[tuple[str, dict]]):
        self._log = log

    async def execute(self, query, params):
        self._log.append((str(query), dict(params)))
        return None


@pytest.fixture
def executed_log():
    return []


@pytest.fixture(autouse=True)
def _wire(monkeypatch, executed_log):
    @asynccontextmanager
    async def fake_get_session():
        yield _RecordingSession(executed_log)

    monkeypatch.setattr(_common, "get_breaker", lambda name: _PassthroughBreaker())
    monkeypatch.setattr(_common, "get_session", fake_get_session)
    monkeypatch.setattr(_common, "detect_anomalies", lambda df, source: df.iloc[0:0])
    monkeypatch.setattr(_common, "record_anomalies", _noop_record_anomalies)


async def _noop_record_anomalies(run_id, source, table, anomalies):
    pass


def _statuses(executed_log, table="meta._ingest_log"):
    return [
        params.get("status")
        for query, params in executed_log
        if table in query and "status" in params
    ]


async def test_non_empty_fetch_stages_publishes_and_logs_staged(
    monkeypatch, executed_log
):
    staged = {}

    def fake_stage_dataframe(df, table, run_id):
        staged["table"] = table
        staged["run_id"] = run_id
        return f"/fake/{table}-{run_id}.duckdb", len(df)

    published = {}

    async def fake_publish(payload):
        published.update(payload)

    monkeypatch.setattr(_common, "stage_dataframe", fake_stage_dataframe)
    monkeypatch.setattr(_common, "publish_landed_event", fake_publish)

    @_common.standard_run("bom", "bom_observations")
    async def fetch(**kwargs):
        return pd.DataFrame({"temp_c": [20, 21, 22]})

    rows = await fetch()

    assert rows == 3
    assert published["source"] == "bom"
    assert published["table"] == "bom_observations"
    assert published["rows"] == 3
    assert (
        published["duckdb_path"] == f"/fake/bom_observations-{staged['run_id']}.duckdb"
    )
    assert _statuses(executed_log) == ["staged"]


async def test_empty_fetch_is_immediately_success_and_does_not_publish(
    monkeypatch, executed_log
):
    monkeypatch.setattr(_common, "stage_dataframe", lambda df, table, run_id: ("", 0))

    published = []

    async def fake_publish(payload):
        published.append(payload)

    monkeypatch.setattr(_common, "publish_landed_event", fake_publish)

    @_common.standard_run("bom", "bom_observations")
    async def fetch(**kwargs):
        return pd.DataFrame()

    rows = await fetch()

    assert rows == 0
    assert published == []
    assert _statuses(executed_log) == ["success"]


async def test_fetch_failure_logs_failed_and_reraises(monkeypatch, executed_log):
    @_common.standard_run("bom", "bom_observations")
    async def fetch(**kwargs):
        raise RuntimeError("upstream down")

    with pytest.raises(RuntimeError, match="upstream down"):
        await fetch()

    assert _statuses(executed_log) == ["failed"]


async def test_non_empty_fetch_increments_ingest_runs_total_success(
    monkeypatch, executed_log
):
    # Distinct source per test -- REGISTRY is process-wide/cumulative, so
    # a real source label shared with other tests would make the exact
    # count assertion below order-dependent (same reasoning as
    # test_metrics.py's own histogram test).
    monkeypatch.setattr(
        _common, "stage_dataframe", lambda df, table, run_id: ("/fake/x.duckdb", 3)
    )
    monkeypatch.setattr(_common, "publish_landed_event", _async_noop)
    before = _ingest_runs_total("ingest_runs_total_test_nonempty", "success")

    @_common.standard_run("ingest_runs_total_test_nonempty", "bom_observations")
    async def fetch(**kwargs):
        return pd.DataFrame({"temp_c": [20, 21, 22]})

    await fetch()

    assert _ingest_runs_total("ingest_runs_total_test_nonempty", "success") == before + 1


async def test_empty_fetch_increments_ingest_runs_total_success(
    monkeypatch, executed_log
):
    monkeypatch.setattr(_common, "stage_dataframe", lambda df, table, run_id: ("", 0))
    before = _ingest_runs_total("ingest_runs_total_test_empty", "success")

    @_common.standard_run("ingest_runs_total_test_empty", "bom_observations")
    async def fetch(**kwargs):
        return pd.DataFrame()

    await fetch()

    assert _ingest_runs_total("ingest_runs_total_test_empty", "success") == before + 1


async def test_fetch_failure_increments_ingest_runs_total_failure(
    monkeypatch, executed_log
):
    before = _ingest_runs_total("ingest_runs_total_test_failure", "failure")

    @_common.standard_run("ingest_runs_total_test_failure", "bom_observations")
    async def fetch(**kwargs):
        raise RuntimeError("upstream down")

    with pytest.raises(RuntimeError):
        await fetch()

    assert _ingest_runs_total("ingest_runs_total_test_failure", "failure") == before + 1


async def test_anomalies_are_recorded_when_detected(monkeypatch, executed_log):
    monkeypatch.setattr(
        _common,
        "stage_dataframe",
        lambda df, table, run_id: ("/fake/x.duckdb", len(df)),
    )
    monkeypatch.setattr(_common, "publish_landed_event", _async_noop)

    def fake_detect(df, source):
        return df.iloc[[0]].assign(anomaly_score=[1.0], anomaly_reason=["out_of_range"])

    recorded = {}

    async def fake_record(run_id, source, table, anomalies):
        recorded["count"] = len(anomalies)
        recorded["source"] = source

    monkeypatch.setattr(_common, "detect_anomalies", fake_detect)
    monkeypatch.setattr(_common, "record_anomalies", fake_record)

    @_common.standard_run("bom", "bom_observations")
    async def fetch(**kwargs):
        return pd.DataFrame({"temp_c": [1000, 20]})

    await fetch()

    assert recorded == {"count": 1, "source": "bom"}


async def _async_noop(*args, **kwargs):
    pass


async def test_log_run_synced_updates_status_and_rows_loaded(executed_log, monkeypatch):
    @asynccontextmanager
    async def fake_get_session():
        yield _RecordingSession(executed_log)

    monkeypatch.setattr(_common, "get_session", fake_get_session)

    run_id = uuid.uuid4()
    await _common.log_run_synced(run_id, 42)

    query, params = executed_log[0]
    assert "status = 'success'" in query
    assert params["rows_loaded"] == 42
    assert params["id"] == str(run_id)


async def test_log_run_sync_failed_updates_status_and_error(executed_log, monkeypatch):
    @asynccontextmanager
    async def fake_get_session():
        yield _RecordingSession(executed_log)

    monkeypatch.setattr(_common, "get_session", fake_get_session)

    run_id = uuid.uuid4()
    await _common.log_run_sync_failed(run_id, "postgres exploded")

    query, params = executed_log[0]
    assert "sync_failed" in query
    assert params["error_message"] == "postgres exploded"
