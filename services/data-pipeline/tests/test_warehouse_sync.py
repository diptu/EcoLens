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

    async def fake_read_staged_with_fallback(
        path, table, run_id, object_storage_key, object_storage_bucket
    ):
        calls["read"] = (path, table, run_id, object_storage_key, object_storage_bucket)
        return pd.DataFrame({"a": [1, 2]})

    monkeypatch.setattr(
        warehouse_sync, "read_staged_with_fallback", fake_read_staged_with_fallback
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
        warehouse_sync,
        "delete_staged",
        lambda path, table, run_id: deleted.setdefault("call", (path, table, run_id)),
    )

    payload = {
        "run_id": "11111111-1111-1111-1111-111111111111",
        "source": "bom",
        "table": "bom_observations",
        "schema": "raw",
        "duckdb_path": "/fake/staging/bom_observations-run.duckdb",
        "object_storage_key": "staging/bom_observations-run.duckdb",
        "object_storage_bucket": "ecolense",
        "rows": 2,
    }

    await warehouse_sync.sync_landed_event(payload)

    assert calls["load"] == ("bom_observations", "raw", 2)
    assert calls["synced"] == ("11111111-1111-1111-1111-111111111111", 2)
    # The object-storage fields from the payload are threaded through to
    # the fallback reader, not silently dropped -- this is exactly what
    # makes cross-machine deployment work (see duckdb_staging.
    # read_staged_with_fallback's own docstring).
    assert calls["read"] == (
        "/fake/staging/bom_observations-run.duckdb",
        "bom_observations",
        "11111111-1111-1111-1111-111111111111",
        "staging/bom_observations-run.duckdb",
        "ecolense",
    )
    assert deleted["call"] == (
        "/fake/staging/bom_observations-run.duckdb",
        "bom_observations",
        "11111111-1111-1111-1111-111111111111",
    )


async def test_sync_landed_event_defaults_object_storage_fields_to_none_when_absent(
    monkeypatch,
):
    """This service's own legacy producer never populates
    object_storage_key/_bucket -- `.get()` on the payload, not `[]`,
    means those events still work rather than raising a `KeyError`."""
    calls = {}

    async def fake_read_staged_with_fallback(
        path, table, run_id, object_storage_key, object_storage_bucket
    ):
        calls["read"] = (object_storage_key, object_storage_bucket)
        return pd.DataFrame({"a": [1]})

    monkeypatch.setattr(
        warehouse_sync, "read_staged_with_fallback", fake_read_staged_with_fallback
    )

    async def fake_load_to_postgres(session, df, table, schema="raw"):
        return 1

    monkeypatch.setattr(warehouse_sync, "load_to_postgres", fake_load_to_postgres)
    monkeypatch.setattr(warehouse_sync, "get_session", _fake_get_session)

    async def fake_log_run_synced(run_id, rows_loaded):
        return None

    monkeypatch.setattr(warehouse_sync, "log_run_synced", fake_log_run_synced)
    monkeypatch.setattr(
        warehouse_sync, "delete_staged", lambda path, table, run_id: None
    )

    payload = {
        "run_id": "33333333-3333-3333-3333-333333333333",
        "source": "bom",
        "table": "bom_observations",
        "duckdb_path": "/fake/staging/bom_observations-run.duckdb",
    }

    await warehouse_sync.sync_landed_event(payload)

    assert calls["read"] == (None, None)


async def test_sync_landed_event_failure_logs_sync_failed_and_reraises(monkeypatch):
    async def boom(path, table, run_id, object_storage_key, object_storage_bucket):
        raise RuntimeError("duckdb file corrupted")

    monkeypatch.setattr(warehouse_sync, "read_staged_with_fallback", boom)

    calls = {}

    async def fake_log_run_sync_failed(run_id, error_message):
        calls["failed"] = (str(run_id), error_message)

    monkeypatch.setattr(warehouse_sync, "log_run_sync_failed", fake_log_run_sync_failed)

    deleted = {"called": False}
    monkeypatch.setattr(
        warehouse_sync,
        "delete_staged",
        lambda path, table, run_id: deleted.__setitem__("called", True),
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
