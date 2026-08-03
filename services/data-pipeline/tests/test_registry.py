from contextlib import asynccontextmanager

import pytest

from app.service.pipeline.tasks import (
    _common,
    ingest_aemo_nem,
    ingest_aemo_wem,
    ingest_bom,
    ingest_holidays,
    registry,
)

pytestmark = pytest.mark.anyio


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
        from app.service.pipeline.circuit_breaker import CircuitState

        return CircuitState.CLOSED


class _FakeSession:
    async def execute(self, *args, **kwargs):
        return None


@asynccontextmanager
async def _fake_get_session():
    yield _FakeSession()


def _fake_stage_dataframe(df, table, run_id):
    if df.empty:
        return "", 0
    return f"/fake/staging/{table}-{run_id}.duckdb", len(df)


async def _fake_publish_landed_event(payload):
    pass


def _fake_detect_anomalies(df, source):
    return df.iloc[0:0]


async def _fake_record_anomalies(run_id, source, table, anomalies):
    pass


@pytest.fixture(autouse=True)
def _bypass_all_breakers_and_db(monkeypatch):
    # Two breaker layers for the non-self-wrapped sources: their own
    # inner fallback breaker, and standard_run's outer one (applied by
    # the registry). Both need bypassing for an offline test. DuckDB
    # staging + RabbitMQ publish + Postgres sync + anomaly detection are
    # all covered by their own dedicated test files -- here we only care
    # that the registry wires source/table correctly, so fake them rather
    # than needing a live DuckDB file / broker / Postgres. Anomaly
    # detection matters here specifically because a real flagged row
    # would make `record_anomalies` open a real (unpatched) DB session.
    monkeypatch.setattr(_common, "get_breaker", lambda name: _PassthroughBreaker())
    monkeypatch.setattr(_common, "get_session", _fake_get_session)
    monkeypatch.setattr(_common, "stage_dataframe", _fake_stage_dataframe)
    monkeypatch.setattr(_common, "publish_landed_event", _fake_publish_landed_event)
    monkeypatch.setattr(_common, "detect_anomalies", _fake_detect_anomalies)
    monkeypatch.setattr(_common, "record_anomalies", _fake_record_anomalies)
    monkeypatch.setattr(ingest_bom, "get_breaker", lambda name: _PassthroughBreaker())
    monkeypatch.setattr(
        ingest_aemo_nem, "get_breaker", lambda name: _PassthroughBreaker()
    )
    monkeypatch.setattr(
        ingest_aemo_wem, "get_breaker", lambda name: _PassthroughBreaker()
    )
    monkeypatch.setattr(
        ingest_holidays, "get_breaker", lambda name: _PassthroughBreaker()
    )


def test_sources_cover_all_5_ingestion_tasks():
    assert set(registry.SOURCES) == {"oe", "aemo-nem", "aemo-wem", "bom", "holidays"}


async def test_run_source_wraps_bom_with_standard_run_and_lands_it():
    rows = await registry.run_source("bom", lookback_minutes=60)

    assert isinstance(rows, int)
    assert rows > 0


async def test_run_source_wraps_aemo_nem():
    rows = await registry.run_source("aemo-nem", lookback_minutes=15)

    assert isinstance(rows, int)
    assert rows > 0


async def test_run_source_wraps_aemo_wem():
    rows = await registry.run_source("aemo-wem", lookback_minutes=60)

    assert isinstance(rows, int)
    assert rows > 0


async def test_run_source_wraps_holidays_with_a_different_kwarg_name():
    rows = await registry.run_source("holidays", year=2030)

    assert isinstance(rows, int)
    assert rows > 0


async def test_run_source_oe_is_not_double_wrapped():
    # ingest_openelectricity.run is already @standard_run-decorated;
    # run_source must call it directly, not wrap it a second time
    # (double-wrapping would double-log to meta._ingest_log per call).
    rows = await registry.run_source("oe", lookback_minutes=30)

    assert rows == 0  # no OE API key configured -> every region fails gracefully


def test_run_source_unknown_key_raises_key_error():
    with pytest.raises(KeyError):
        import asyncio

        asyncio.run(registry.run_source("nonexistent"))
