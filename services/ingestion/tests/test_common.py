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
    monkeypatch.setattr(_common, "upload_staged_file", _fake_upload_staged_file)


async def _noop_record_anomalies(run_id, source, table, anomalies):
    pass


async def _fake_upload_staged_file(path, table, run_id):
    return f"staging/{table}-{run_id}.duckdb" if path else None


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
    publish_kwargs = {}

    async def fake_publish(payload, **kwargs):
        published.update(payload)
        publish_kwargs.update(kwargs)

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
    assert (
        published["object_storage_key"]
        == f"staging/bom_observations-{staged['run_id']}.duckdb"
    )
    assert published["object_storage_bucket"]
    assert published["window_start"] is None
    assert published["window_end"] is None
    assert publish_kwargs["queue_name"] is None  # not a shadow run
    assert _statuses(executed_log) == ["staged"]


async def test_published_event_carries_the_real_window_for_a_backfill_run(
    monkeypatch,
):
    """`registry.run_source`'s own docstring covers the real bug this
    guards against: `window_start`/`window_end` used to only reach
    `meta._ingest_log`, never the published event itself, even for a
    real backfill run with a genuine date range."""

    def fake_stage_dataframe(df, table, run_id):
        return f"/fake/{table}-{run_id}.duckdb", len(df)

    published = {}

    async def fake_publish(payload, **kwargs):
        published.update(payload)

    monkeypatch.setattr(_common, "stage_dataframe", fake_stage_dataframe)
    monkeypatch.setattr(_common, "publish_landed_event", fake_publish)

    @_common.standard_run(
        "bom",
        "bom_observations",
        window_start="2026-01-01T00:00:00+00:00",
        window_end="2026-01-02T00:00:00+00:00",
    )
    async def fetch(**kwargs):
        return pd.DataFrame({"temp_c": [20, 21, 22]})

    await fetch()

    assert published["window_start"] == "2026-01-01T00:00:00+00:00"
    assert published["window_end"] == "2026-01-02T00:00:00+00:00"


async def test_empty_fetch_is_immediately_success_and_does_not_publish(
    monkeypatch, executed_log
):
    monkeypatch.setattr(_common, "stage_dataframe", lambda df, table, run_id: ("", 0))

    published = []

    async def fake_publish(payload, **kwargs):
        published.append(payload)

    monkeypatch.setattr(_common, "publish_landed_event", fake_publish)

    @_common.standard_run("bom", "bom_observations")
    async def fetch(**kwargs):
        return pd.DataFrame()

    rows = await fetch()

    assert rows == 0
    assert published == []
    assert _statuses(executed_log) == ["success"]


async def test_shadow_triggered_run_publishes_to_the_shadow_queue(
    monkeypatch, executed_log
):
    """Phase 4's "Execute Shadow Runs" -- `triggered_by="shadow"` must
    route to `Settings.rabbitmq_landing_queue_shadow`, not the real
    landing queue, so the real warehouse-sync consumer never picks it up
    and double-loads `raw.*` from an independent fetch of the same
    window."""
    from app.core.config import get_settings

    monkeypatch.setattr(
        _common, "stage_dataframe", lambda df, table, run_id: ("/fake/x.duckdb", 1)
    )
    publish_kwargs = {}

    async def fake_publish(payload, **kwargs):
        publish_kwargs.update(kwargs)

    monkeypatch.setattr(_common, "publish_landed_event", fake_publish)

    @_common.standard_run("bom", "bom_observations", triggered_by="shadow")
    async def fetch(**kwargs):
        return pd.DataFrame({"temp_c": [20]})

    await fetch()

    assert publish_kwargs["queue_name"] == get_settings().rabbitmq_landing_queue_shadow


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


def _json_lines(text: str) -> list[dict]:
    import json

    return [json.loads(line) for line in text.strip().splitlines() if line.strip()]


class TestStructuredLoggingParity:
    """`services/ingestion/TODO.md` Phase 3, "Standardize Structured
    Logging" -- `standard_run` must emit the same named events data-
    pipeline's identical module does (`ingest.run_started`/`ingest.
    run_staged`/`ingest.run_failed`, each carrying `source`/`run_id`),
    so external monitoring queries written against one service's logs
    keep working unchanged against the other's. Asserted against the
    real JSON lines `configure_logging`'s `PrintLoggerFactory` writes to
    stdout (`capsys`), not `structlog.testing.capture_logs` -- `_common.
    log` is a module-level logger created at import time under
    `cache_logger_on_first_use=True`, so by the time any test runs it's
    already bound to the processor chain active at first use; `capture_
    logs`'s config patch only affects loggers resolved *after* it's
    entered, so it silently captures nothing here. Real stdout output is
    what an external log aggregator actually parses anyway, so it's the
    more honest thing to assert against.
    """

    async def test_a_staged_run_emits_run_started_then_run_staged(
        self, monkeypatch, executed_log, capsys
    ):
        monkeypatch.setattr(
            _common, "stage_dataframe", lambda df, table, run_id: ("/fake/x.duckdb", 1)
        )
        monkeypatch.setattr(_common, "publish_landed_event", _async_noop)

        @_common.standard_run("bom", "bom_observations")
        async def fetch(**kwargs):
            return pd.DataFrame({"temp_c": [20]})

        rows = await fetch()

        lines = _json_lines(capsys.readouterr().out)
        events = [line["event"] for line in lines]
        assert "ingest.run_started" in events
        assert "ingest.run_staged" in events
        started = next(line for line in lines if line["event"] == "ingest.run_started")
        staged = next(line for line in lines if line["event"] == "ingest.run_staged")
        assert started["source"] == "bom"
        assert staged["source"] == "bom"
        assert started["run_id"] == staged["run_id"]
        assert rows == 1

    async def test_a_failed_fetch_emits_run_started_then_run_failed(
        self, executed_log, capsys
    ):
        @_common.standard_run("bom", "bom_observations")
        async def fetch(**kwargs):
            raise RuntimeError("upstream down")

        with pytest.raises(RuntimeError):
            await fetch()

        lines = _json_lines(capsys.readouterr().out)
        events = [line["event"] for line in lines]
        assert "ingest.run_started" in events
        assert "ingest.run_failed" in events
        failed = next(line for line in lines if line["event"] == "ingest.run_failed")
        assert failed["source"] == "bom"
        assert failed["error"] == "upstream down"

    async def test_an_empty_fetch_emits_run_started_then_run_succeeded(
        self, monkeypatch, executed_log, capsys
    ):
        monkeypatch.setattr(
            _common, "stage_dataframe", lambda df, table, run_id: ("", 0)
        )

        @_common.standard_run("bom", "bom_observations")
        async def fetch(**kwargs):
            return pd.DataFrame()

        await fetch()

        lines = _json_lines(capsys.readouterr().out)
        events = [line["event"] for line in lines]
        assert "ingest.run_started" in events
        assert "ingest.run_succeeded" in events
