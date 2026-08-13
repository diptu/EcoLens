from unittest.mock import AsyncMock

import duckdb
import pandas as pd
import pytest

from app.core.config import get_settings
from app.db import object_storage
from app.db.duckdb_client import read_run, read_run_with_fallback, staging_path


@pytest.fixture(autouse=True)
def _staging_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_STAGING_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _write_shared_file(table: str, rows: list[dict]) -> None:
    path = staging_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    try:
        df = pd.DataFrame(rows)
        con.register("df_view", df)
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM df_view")  # nosec B608
    finally:
        con.close()


def test_read_run_returns_empty_when_the_shared_file_does_not_exist_yet():
    result = read_run("bom_observations", "run-1")

    assert result.empty


def test_read_run_returns_empty_when_the_table_does_not_exist():
    _write_shared_file("bom_observations", [{"a": 1, "_ingest_run_id": "run-1"}])

    result = read_run("aemo_nem_dispatch", "run-1")

    assert result.empty


def test_read_run_filters_by_run_id_and_excludes_the_bookkeeping_column():
    _write_shared_file(
        "bom_observations",
        [
            {"a": 1, "_ingest_run_id": "run-1"},
            {"a": 2, "_ingest_run_id": "run-2"},
        ],
    )

    result = read_run("bom_observations", "run-2")

    assert result["a"].tolist() == [2]
    assert "_ingest_run_id" not in result.columns


def test_read_run_returns_empty_for_an_unknown_run_id():
    _write_shared_file("bom_observations", [{"a": 1, "_ingest_run_id": "run-1"}])

    result = read_run("bom_observations", "run-nonexistent")

    assert result.empty


@pytest.mark.anyio
class TestReadRunWithFallback:
    """The cross-machine case: `services/ingestion` ran on a different
    host than this consumer, so the shared `duckdb_staging` volume they'd
    otherwise share isn't actually shared -- `staging_path()` never
    exists locally."""

    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    def _patch_download(self, monkeypatch, body: bytes):
        download = AsyncMock(return_value=body)
        monkeypatch.setattr(object_storage, "download_bytes", download)
        return download

    def _snapshot_bytes(self, rows: list[dict]) -> bytes:
        # Same shape `services/ingestion`'s `_export_run_snapshot`
        # uploads: a fixed `landed` table, just this run's rows, no
        # `_ingest_run_id` column.
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.gettempdir()) / "test-waerehouse-snapshot-source.duckdb"
        tmp.unlink(missing_ok=True)
        con = duckdb.connect(str(tmp))
        try:
            df = pd.DataFrame(rows)
            con.register("df_view", df)
            con.execute("CREATE TABLE landed AS SELECT * FROM df_view")
        finally:
            con.close()
        body = tmp.read_bytes()
        tmp.unlink(missing_ok=True)
        return body

    async def test_reads_locally_without_touching_object_storage_when_the_shared_file_exists(
        self, monkeypatch
    ):
        _write_shared_file(
            "bom_observations",
            [{"a": 1, "_ingest_run_id": "run-1"}, {"a": 2, "_ingest_run_id": "run-2"}],
        )
        download = self._patch_download(monkeypatch, b"")

        result = await read_run_with_fallback(
            "bom_observations", "run-2", "some/key.duckdb", "some-bucket"
        )

        assert result["a"].tolist() == [2]
        download.assert_not_called()

    async def test_downloads_and_reads_the_snapshot_when_the_shared_file_is_missing(
        self, monkeypatch
    ):
        body = self._snapshot_bytes([{"a": 10}, {"a": 20}])
        download = self._patch_download(monkeypatch, body)

        result = await read_run_with_fallback(
            "bom_observations",
            "run-remote",
            "staging/bom_observations-run-remote.duckdb",
            "ecolense",
        )

        assert result["a"].tolist() == [10, 20]
        download.assert_awaited_once_with(
            "staging/bom_observations-run-remote.duckdb", bucket="ecolense"
        )

    async def test_cleans_up_the_downloaded_temp_file_afterward(self, monkeypatch):
        import tempfile
        from pathlib import Path

        body = self._snapshot_bytes([{"a": 1}])
        self._patch_download(monkeypatch, body)

        await read_run_with_fallback(
            "bom_observations", "run-cleanup", "some/key.duckdb", "bucket"
        )

        tmp_path = Path(tempfile.gettempdir()) / "remote-bom_observations-run-cleanup.duckdb"
        assert not tmp_path.exists()

    async def test_falls_through_to_read_run_when_no_object_storage_key(self):
        # No shared file, no object-storage key -- same honest empty
        # result `read_run` always returned, not a new error class.
        result = await read_run_with_fallback("bom_observations", "run-x", None, None)

        assert result.empty
