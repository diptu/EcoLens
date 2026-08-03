from contextlib import asynccontextmanager

import pandas as pd
import pytest

from app.service.pipeline import warehouse_sync

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeSession:
    pass


@asynccontextmanager
async def _fake_get_session():
    yield _FakeSession()


async def test_sync_landed_event_happy_path(monkeypatch):
    calls = {}

    monkeypatch.setattr(
        warehouse_sync, "read_staged", lambda path: pd.DataFrame({"a": [1, 2]})
    )

    async def fake_load_to_postgres(session, df, table, schema="raw"):
        calls["load"] = (table, schema, len(df))
        return 2

    monkeypatch.setattr(warehouse_sync, "load_to_postgres", fake_load_to_postgres)
    monkeypatch.setattr(warehouse_sync, "get_session", _fake_get_session)

    async def fake_log_run_synced(run_id, rows_loaded):
        calls["synced"] = (str(run_id), rows_loaded)

    monkeypatch.setattr(warehouse_sync, "log_run_synced", fake_log_run_synced)

    deleted = {}
    monkeypatch.setattr(
        warehouse_sync, "delete_staged", lambda path: deleted.setdefault("path", path)
    )

    payload = {
        "run_id": "11111111-1111-1111-1111-111111111111",
        "source": "bom",
        "table": "bom_observations",
        "schema": "raw",
        "duckdb_path": "/fake/staging/bom_observations-run.duckdb",
        "rows": 2,
    }

    await warehouse_sync.sync_landed_event(payload)

    assert calls["load"] == ("bom_observations", "raw", 2)
    assert calls["synced"] == ("11111111-1111-1111-1111-111111111111", 2)
    assert deleted["path"] == "/fake/staging/bom_observations-run.duckdb"


async def test_sync_landed_event_failure_logs_sync_failed_and_reraises(monkeypatch):
    def boom(path):
        raise RuntimeError("duckdb file corrupted")

    monkeypatch.setattr(warehouse_sync, "read_staged", boom)

    calls = {}

    async def fake_log_run_sync_failed(run_id, error_message):
        calls["failed"] = (str(run_id), error_message)

    monkeypatch.setattr(warehouse_sync, "log_run_sync_failed", fake_log_run_sync_failed)

    deleted = {"called": False}
    monkeypatch.setattr(
        warehouse_sync,
        "delete_staged",
        lambda path: deleted.__setitem__("called", True),
    )

    payload = {
        "run_id": "22222222-2222-2222-2222-222222222222",
        "source": "bom",
        "table": "bom_observations",
        "duckdb_path": "/fake/staging/missing.duckdb",
    }

    with pytest.raises(RuntimeError, match="duckdb file corrupted"):
        await warehouse_sync.sync_landed_event(payload)

    assert calls["failed"][0] == "22222222-2222-2222-2222-222222222222"
    assert "duckdb file corrupted" in calls["failed"][1]
    # The DuckDB file is deliberately left on disk as the recovery
    # artifact -- delete_staged must not be called on the failure path.
    assert deleted["called"] is False
