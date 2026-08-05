import pandas as pd
import pytest

from app.core.config import get_settings
from app.service.pipeline.duckdb_staging import (
    delete_staged,
    read_staged,
    stage_dataframe,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _staging_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_STAGING_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_stage_dataframe_writes_a_file_and_returns_row_count():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})

    path, rows = stage_dataframe(df, "bom_observations", "run-1")

    assert rows == 3
    assert path.endswith("bom_observations-run-1.duckdb")
    import os

    assert os.path.exists(path)


def test_stage_dataframe_empty_df_is_a_no_op():
    df = pd.DataFrame({"a": []})

    path, rows = stage_dataframe(df, "bom_observations", "run-2")

    assert (path, rows) == ("", 0)


def test_read_staged_roundtrips_the_dataframe():
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    path, _ = stage_dataframe(df, "bom_observations", "run-3")

    result = read_staged(path, "bom_observations", "run-3")

    assert result.equals(df)


def test_delete_staged_removes_the_file():
    import os

    df = pd.DataFrame({"a": [1]})
    path, _ = stage_dataframe(df, "bom_observations", "run-4")
    assert os.path.exists(path)

    delete_staged(path, "bom_observations", "run-4")

    assert not os.path.exists(path)


def test_delete_staged_is_idempotent_on_a_missing_file():
    # Should not raise -- a retried consumer run may see a file that was
    # already cleaned up by an earlier attempt.
    delete_staged(
        "/nonexistent/path/does-not-exist.duckdb", "bom_observations", "run-x"
    )


def test_different_runs_get_independent_files():
    df1 = pd.DataFrame({"a": [1]})
    df2 = pd.DataFrame({"a": [2, 3]})

    path1, rows1 = stage_dataframe(df1, "bom_observations", "run-a")
    path2, rows2 = stage_dataframe(df2, "bom_observations", "run-b")

    assert path1 != path2
    assert rows1 == 1
    assert rows2 == 2
    assert read_staged(path1, "bom_observations", "run-a")["a"].tolist() == [1]
    assert read_staged(path2, "bom_observations", "run-b")["a"].tolist() == [2, 3]


class TestSharedFileShape:
    """`services/ingestion`'s newer producer writes a different on-disk
    shape than this service's own `stage_dataframe` -- a single shared
    file, one real per-source table many runs append into, rows tagged
    `_ingest_run_id`. `read_staged`/`delete_staged` fall back to this
    shape whenever the legacy fixed `landed` table isn't present (see
    `duckdb_staging.py`'s own module docstring)."""

    def _write_shared_file(self, tmp_path, table, rows):
        import duckdb

        path = tmp_path / "landed.duckdb"
        con = duckdb.connect(str(path))
        try:
            df = pd.DataFrame(rows)
            con.register("df_view", df)
            con.execute(f"CREATE TABLE {table} AS SELECT * FROM df_view")  # nosec B608
        finally:
            con.close()
        return str(path)

    def test_read_staged_filters_by_run_id_within_the_shared_table(self, tmp_path):
        path = self._write_shared_file(
            tmp_path,
            "bom_observations",
            [
                {"a": 1, "_ingest_run_id": "run-1"},
                {"a": 2, "_ingest_run_id": "run-2"},
            ],
        )

        result = read_staged(path, "bom_observations", "run-2")

        assert result["a"].tolist() == [2]
        assert "_ingest_run_id" not in result.columns

    def test_delete_staged_removes_only_that_runs_rows_not_the_file(self, tmp_path):
        import os

        path = self._write_shared_file(
            tmp_path,
            "bom_observations",
            [
                {"a": 1, "_ingest_run_id": "run-1"},
                {"a": 2, "_ingest_run_id": "run-2"},
            ],
        )

        delete_staged(path, "bom_observations", "run-1")

        assert os.path.exists(path)
        remaining = read_staged(path, "bom_observations", "run-2")
        assert remaining["a"].tolist() == [2]
