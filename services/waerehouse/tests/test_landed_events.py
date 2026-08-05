from contextlib import asynccontextmanager

import pandas as pd
import pytest

from app.consumers import landed_events

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeSession:
    pass


def _fake_get_session():
    @asynccontextmanager
    async def _get_session():
        yield _FakeSession()

    return _get_session


PAYLOAD = {
    "run_id": "11111111-1111-1111-1111-111111111111",
    "source": "bom",
    "table": "bom_observations",
    "schema": "raw",
}


async def test_happy_path_reads_loads_and_marks_synced(monkeypatch):
    calls = {}

    monkeypatch.setattr(
        landed_events, "read_run", lambda table, run_id: pd.DataFrame({"a": [1, 2]})
    )
    monkeypatch.setattr(landed_events, "get_session", _fake_get_session())

    async def fake_load_to_postgres(session, df, table, schema="raw"):
        calls["load"] = (table, schema, len(df))
        return 2

    monkeypatch.setattr(landed_events, "load_to_postgres", fake_load_to_postgres)

    async def fake_mark_synced(session, run_id, rows_loaded):
        calls["synced"] = (str(run_id), rows_loaded)

    monkeypatch.setattr(landed_events, "mark_synced", fake_mark_synced)

    await landed_events.sync_landed_event(PAYLOAD)

    assert calls["load"] == ("bom_observations", "raw", 2)
    assert calls["synced"] == ("11111111-1111-1111-1111-111111111111", 2)


async def test_failure_marks_sync_failed_and_reraises(monkeypatch):
    def boom(table, run_id):
        raise RuntimeError("duckdb file corrupted")

    monkeypatch.setattr(landed_events, "read_run", boom)
    monkeypatch.setattr(landed_events, "get_session", _fake_get_session())

    calls = {}

    async def fake_mark_sync_failed(session, run_id, error_message):
        calls["failed"] = (str(run_id), error_message)

    monkeypatch.setattr(landed_events, "mark_sync_failed", fake_mark_sync_failed)

    with pytest.raises(RuntimeError, match="duckdb file corrupted"):
        await landed_events.sync_landed_event(PAYLOAD)

    assert calls["failed"][0] == "11111111-1111-1111-1111-111111111111"
    assert "duckdb file corrupted" in calls["failed"][1]


async def test_defaults_schema_to_raw_when_absent(monkeypatch):
    payload = {k: v for k, v in PAYLOAD.items() if k != "schema"}
    captured = {}

    monkeypatch.setattr(
        landed_events, "read_run", lambda table, run_id: pd.DataFrame({"a": [1]})
    )
    monkeypatch.setattr(landed_events, "get_session", _fake_get_session())

    async def fake_load_to_postgres(session, df, table, schema="raw"):
        captured["schema"] = schema
        return 1

    monkeypatch.setattr(landed_events, "load_to_postgres", fake_load_to_postgres)

    async def fake_mark_synced(session, run_id, rows_loaded):
        pass

    monkeypatch.setattr(landed_events, "mark_synced", fake_mark_synced)

    await landed_events.sync_landed_event(payload)

    assert captured["schema"] == "raw"
