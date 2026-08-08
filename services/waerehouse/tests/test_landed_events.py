import asyncio
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


@pytest.fixture(autouse=True)
def _no_real_scheduled_build_trigger(monkeypatch):
    """`sync_landed_event`'s success path now also fires
    `_trigger_scheduled_build_in_background()` (a real, fire-and-forget
    `asyncio.ensure_future`) -- without this, every success-path test in
    this file would schedule a background task that opens a real DB
    session (`app.dbt.scheduler.trigger_build_if_due`) with no test
    database to connect to. Default no-op; tests that actually want to
    observe this behavior override it themselves (see
    `TestScheduledBuildTrigger` below)."""

    async def _noop(*args, **kwargs):
        return False

    monkeypatch.setattr(landed_events, "trigger_build_if_due", _noop)


PAYLOAD = {
    "run_id": "11111111-1111-1111-1111-111111111111",
    "source": "bom",
    "table": "bom_observations",
    "schema": "raw",
    "object_storage_key": "staging/bom_observations-11111111-1111-1111-1111-111111111111.duckdb",
    "object_storage_bucket": "ecolense",
}


async def test_happy_path_reads_loads_and_marks_synced(monkeypatch):
    calls = {}

    async def fake_read_run_with_fallback(table, run_id, object_storage_key, object_storage_bucket):
        calls["read"] = (table, run_id, object_storage_key, object_storage_bucket)
        return pd.DataFrame({"a": [1, 2]})

    monkeypatch.setattr(
        landed_events, "read_run_with_fallback", fake_read_run_with_fallback
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
    # The object-storage fields from the payload are threaded through to
    # the fallback reader, not silently dropped -- this is what makes
    # cross-machine deployment work (see duckdb_client.
    # read_run_with_fallback's own docstring).
    assert calls["read"] == (
        "bom_observations",
        "11111111-1111-1111-1111-111111111111",
        "staging/bom_observations-11111111-1111-1111-1111-111111111111.duckdb",
        "ecolense",
    )


async def test_failure_marks_sync_failed_and_reraises(monkeypatch):
    async def boom(table, run_id, object_storage_key, object_storage_bucket):
        raise RuntimeError("duckdb file corrupted")

    monkeypatch.setattr(landed_events, "read_run_with_fallback", boom)
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

    async def fake_read_run_with_fallback(table, run_id, object_storage_key, object_storage_bucket):
        return pd.DataFrame({"a": [1]})

    monkeypatch.setattr(
        landed_events, "read_run_with_fallback", fake_read_run_with_fallback
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


async def test_defaults_object_storage_fields_to_none_when_absent(monkeypatch):
    """A hypothetical event with no object-storage info (shouldn't happen
    for a `services/ingestion`-produced event, but `.get()` not `[]`
    means it wouldn't raise a `KeyError` if it ever did)."""
    payload = {k: v for k, v in PAYLOAD.items() if not k.startswith("object_storage_")}
    calls = {}

    async def fake_read_run_with_fallback(table, run_id, object_storage_key, object_storage_bucket):
        calls["read"] = (object_storage_key, object_storage_bucket)
        return pd.DataFrame({"a": [1]})

    monkeypatch.setattr(
        landed_events, "read_run_with_fallback", fake_read_run_with_fallback
    )
    monkeypatch.setattr(landed_events, "get_session", _fake_get_session())

    async def fake_load_to_postgres(session, df, table, schema="raw"):
        return 1

    monkeypatch.setattr(landed_events, "load_to_postgres", fake_load_to_postgres)

    async def fake_mark_synced(session, run_id, rows_loaded):
        pass

    monkeypatch.setattr(landed_events, "mark_synced", fake_mark_synced)

    await landed_events.sync_landed_event(payload)

    assert calls["read"] == (None, None)


class TestScheduledBuildTrigger:
    """`_trigger_scheduled_build_in_background` -- `TODO.md`'s "Scheduled
    Execution Runner": a real `dbt build` fires off the back of new data
    actually landing, not just a manual/dashboard trigger."""

    async def _sync_happy_path(self, monkeypatch) -> None:
        async def fake_read_run_with_fallback(table, run_id, object_storage_key, object_storage_bucket):
            return pd.DataFrame({"a": [1]})

        monkeypatch.setattr(
            landed_events, "read_run_with_fallback", fake_read_run_with_fallback
        )
        monkeypatch.setattr(landed_events, "get_session", _fake_get_session())

        async def fake_load_to_postgres(session, df, table, schema="raw"):
            return 1

        monkeypatch.setattr(landed_events, "load_to_postgres", fake_load_to_postgres)

        async def fake_mark_synced(session, run_id, rows_loaded):
            pass

        monkeypatch.setattr(landed_events, "mark_synced", fake_mark_synced)

        await landed_events.sync_landed_event(PAYLOAD)

    async def test_a_successful_sync_schedules_the_build_check(self, monkeypatch):
        calls = []

        async def fake_trigger_build_if_due(db):
            calls.append(db)
            return True

        monkeypatch.setattr(
            landed_events, "trigger_build_if_due", fake_trigger_build_if_due
        )

        await self._sync_happy_path(monkeypatch)
        # The trigger is fire-and-forget (`asyncio.ensure_future`), not
        # awaited inline -- yield control once so the scheduled task
        # actually runs before asserting on it.
        await asyncio.sleep(0)

        assert len(calls) == 1

    async def test_a_failing_scheduled_build_check_does_not_raise(self, monkeypatch):
        """The whole point of firing this in the background is that a
        broken scheduled-build check must never affect the sync it was
        triggered from -- that sync already succeeded and is already
        committed by the time this runs."""

        async def fake_trigger_build_if_due(db):
            raise RuntimeError("dbt binary not found")

        monkeypatch.setattr(
            landed_events, "trigger_build_if_due", fake_trigger_build_if_due
        )

        # Must not raise, even though the background task itself does.
        await self._sync_happy_path(monkeypatch)
        await asyncio.sleep(0)

    async def test_a_failed_sync_never_schedules_the_build_check(self, monkeypatch):
        calls = []

        async def fake_trigger_build_if_due(db):
            calls.append(db)
            return True

        monkeypatch.setattr(
            landed_events, "trigger_build_if_due", fake_trigger_build_if_due
        )

        async def boom(table, run_id, object_storage_key, object_storage_bucket):
            raise RuntimeError("duckdb file corrupted")

        monkeypatch.setattr(landed_events, "read_run_with_fallback", boom)
        monkeypatch.setattr(landed_events, "get_session", _fake_get_session())

        async def fake_mark_sync_failed(session, run_id, error_message):
            pass

        monkeypatch.setattr(landed_events, "mark_sync_failed", fake_mark_sync_failed)

        with pytest.raises(RuntimeError, match="duckdb file corrupted"):
            await landed_events.sync_landed_event(PAYLOAD)
        await asyncio.sleep(0)

        assert calls == []
