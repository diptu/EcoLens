from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.db import object_storage
from app.retention import cold_storage

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows, rowcount=0):
        self._rows = rows
        self._rowcount = rowcount
        self.executed: list[str] = []

    async def execute(self, query, params=None):
        sql = str(query)
        self.executed.append(sql)
        if sql.strip().startswith("SELECT"):
            return _FakeResult(self._rows)

        class _DeleteResult:
            rowcount = self._rowcount

        return _DeleteResult()


def _fake_get_session(rows, rowcount=0):
    session = _FakeSession(rows, rowcount)

    @asynccontextmanager
    async def get_session():
        yield session

    return get_session, session


class TestExportTable:
    async def test_skips_export_when_the_key_already_exists(self, monkeypatch):
        monkeypatch.setattr(
            object_storage, "object_exists", AsyncMock(return_value=True)
        )
        upload_bytes = AsyncMock()
        monkeypatch.setattr(object_storage, "upload_bytes", upload_bytes)

        from datetime import UTC, datetime

        session = _FakeSession([])
        key = await cold_storage.export_table(
            session, "aemo_nem_dispatch", "ts", datetime.now(UTC)
        )

        assert key is not None
        upload_bytes.assert_not_awaited()

    async def test_returns_none_when_there_is_nothing_to_export(self, monkeypatch):
        monkeypatch.setattr(
            object_storage, "object_exists", AsyncMock(return_value=False)
        )
        upload_bytes = AsyncMock()
        monkeypatch.setattr(object_storage, "upload_bytes", upload_bytes)

        from datetime import UTC, datetime

        session = _FakeSession([])
        key = await cold_storage.export_table(
            session, "aemo_nem_dispatch", "ts", datetime.now(UTC)
        )

        assert key is None
        upload_bytes.assert_not_awaited()

    async def test_uploads_a_parquet_file_when_rows_exist(self, monkeypatch):
        monkeypatch.setattr(
            object_storage, "object_exists", AsyncMock(return_value=False)
        )
        captured = {}

        async def fake_upload_bytes(key, body):
            captured["key"] = key
            captured["body"] = body
            return f"s3://bucket/{key}"

        monkeypatch.setattr(object_storage, "upload_bytes", fake_upload_bytes)

        from datetime import UTC, datetime

        rows = [{"ts": "2026-01-01", "region": "NSW1", "demand_mw": 8000}]
        session = _FakeSession(rows)

        key = await cold_storage.export_table(
            session, "aemo_nem_dispatch", "ts", datetime.now(UTC)
        )

        assert key is not None
        assert key.endswith(".parquet")
        assert "aemo_nem_dispatch" in key
        assert captured["body"][:4] == b"PAR1"  # parquet magic bytes


class TestExportAndPrune:
    async def test_nothing_to_do_when_all_tables_are_empty(self, monkeypatch):
        get_session, _ = _fake_get_session([])
        monkeypatch.setattr(cold_storage, "get_session", get_session)

        result = await cold_storage.export_and_prune()

        assert result == {}

    async def test_exports_before_pruning_and_reports_both_counts(self, monkeypatch):
        monkeypatch.setattr(
            object_storage, "object_exists", AsyncMock(return_value=False)
        )
        monkeypatch.setattr(
            object_storage, "upload_bytes", AsyncMock(return_value="s3://x")
        )

        rows = [
            {"ts": "2025-01-01", "region": "NSW1"},
            {"ts": "2025-01-02", "region": "QLD1"},
        ]
        get_session, session = _fake_get_session(rows, rowcount=2)
        monkeypatch.setattr(cold_storage, "get_session", get_session)

        result = await cold_storage.export_and_prune(days=60)

        for table_result in result.values():
            assert table_result == {"exported": 2, "pruned": 2}
        assert set(result.keys()) == {
            "aemo_nem_dispatch",
            "aemo_wem_dispatch",
            "bom_observations",
            "openelectricity_mix",
        }

    async def test_does_not_prune_a_table_whose_export_failed(self, monkeypatch):
        """One table's R2 hiccup must not abort the whole retention run
        -- same 'isolate the failure, keep going' philosophy the
        RabbitMQ consumer/Celery fan-out already use elsewhere in this
        codebase."""
        monkeypatch.setattr(
            object_storage, "object_exists", AsyncMock(return_value=False)
        )
        monkeypatch.setattr(
            object_storage,
            "upload_bytes",
            AsyncMock(side_effect=RuntimeError("R2 unreachable")),
        )

        rows = [{"ts": "2025-01-01", "region": "NSW1"}]
        get_session, session = _fake_get_session(rows, rowcount=99)
        monkeypatch.setattr(cold_storage, "get_session", get_session)

        result = await cold_storage.export_and_prune(days=60)

        # Every table's export fails the same way here, so none of them
        # end up in the result, and -- the actual point of this test --
        # the DELETE is never reached for a table whose export failed.
        assert result == {}
        assert not any("DELETE" in sql for sql in session.executed)
