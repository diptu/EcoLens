import os
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from app.core.config import get_settings
from app.service import object_storage
from app.service.pipeline.duckdb_staging import (
    delete_staged,
    read_staged,
    stage_dataframe,
    upload_staged_file,
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


def test_stage_dataframe_writes_the_shared_file_and_returns_row_count():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})

    path, rows = stage_dataframe(df, "bom_observations", "run-1")

    assert rows == 3
    assert path.endswith("landed.duckdb")
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


def test_two_runs_of_the_same_source_share_one_file(tmp_path):
    df1 = pd.DataFrame({"a": [1]})
    df2 = pd.DataFrame({"a": [2, 3]})

    path1, rows1 = stage_dataframe(df1, "bom_observations", "run-a")
    path2, rows2 = stage_dataframe(df2, "bom_observations", "run-b")

    assert path1 == path2  # the whole point: one shared file, not per-run
    assert rows1 == 1
    assert rows2 == 2
    # Only this repo's own single landed.duckdb file exists under the
    # staging dir -- no per-run files scattered alongside it.
    duckdb_files = list(tmp_path.glob("*.duckdb"))
    assert len(duckdb_files) == 1

    assert read_staged(path1, "bom_observations", "run-a")["a"].tolist() == [1]
    assert read_staged(path2, "bom_observations", "run-b")["a"].tolist() == [2, 3]


def test_different_sources_get_their_own_table_in_the_shared_file():
    df_bom = pd.DataFrame({"temp_c": [20.0]})
    df_nem = pd.DataFrame({"demand_mw": [8000]})

    path_bom, _ = stage_dataframe(df_bom, "bom_observations", "run-x")
    path_nem, _ = stage_dataframe(df_nem, "aemo_nem_dispatch", "run-y")

    assert path_bom == path_nem
    bom_rows = read_staged(path_bom, "bom_observations", "run-x")
    nem_rows = read_staged(path_nem, "aemo_nem_dispatch", "run-y")
    assert bom_rows["temp_c"].tolist() == [20.0]
    assert nem_rows["demand_mw"].tolist() == [8000]


def test_a_later_run_with_a_new_column_does_not_break_earlier_rows():
    """Forward schema drift: a later run's df has a column an earlier
    run's didn't. `INSERT ... BY NAME` would otherwise reject this
    outright -- `_add_missing_columns` ALTERs the table first."""
    df1 = pd.DataFrame({"a": [1]})
    df2 = pd.DataFrame({"a": [2], "b": ["new-column"]})

    path, _ = stage_dataframe(df1, "bom_observations", "run-1")
    stage_dataframe(df2, "bom_observations", "run-2")

    run1_rows = read_staged(path, "bom_observations", "run-1")
    run2_rows = read_staged(path, "bom_observations", "run-2")
    assert run1_rows["b"].isna().all()
    assert run2_rows["b"].tolist() == ["new-column"]


def test_delete_staged_removes_only_that_runs_rows():
    df1 = pd.DataFrame({"a": [1]})
    df2 = pd.DataFrame({"a": [2]})
    path, _ = stage_dataframe(df1, "bom_observations", "run-1")
    stage_dataframe(df2, "bom_observations", "run-2")

    delete_staged(path, "bom_observations", "run-1")

    assert read_staged(path, "bom_observations", "run-1").empty
    assert read_staged(path, "bom_observations", "run-2")["a"].tolist() == [2]
    assert os.path.exists(path)  # the shared file itself is never deleted


def test_delete_staged_is_idempotent_on_a_missing_file():
    # Should not raise -- a retried consumer run may see a file that was
    # already cleaned up by an earlier attempt.
    delete_staged(
        "/nonexistent/path/does-not-exist.duckdb", "bom_observations", "run-1"
    )


def test_delete_staged_is_idempotent_on_an_already_deleted_run():
    df = pd.DataFrame({"a": [1]})
    path, _ = stage_dataframe(df, "bom_observations", "run-1")

    delete_staged(path, "bom_observations", "run-1")
    delete_staged(path, "bom_observations", "run-1")  # should not raise

    assert read_staged(path, "bom_observations", "run-1").empty


async def test_upload_staged_file_is_a_noop_for_an_empty_fetch(monkeypatch):
    upload_file = AsyncMock()
    monkeypatch.setattr(object_storage, "upload_file", upload_file)

    key = await upload_staged_file("", "bom_observations", "run-5")

    assert key is None
    upload_file.assert_not_awaited()


async def test_upload_staged_file_uploads_a_run_scoped_snapshot(monkeypatch):
    df1 = pd.DataFrame({"a": [1]})
    df2 = pd.DataFrame({"a": [2]})
    path, _ = stage_dataframe(df1, "bom_observations", "run-6")
    stage_dataframe(df2, "bom_observations", "run-6b")

    monkeypatch.setattr(object_storage, "object_exists", AsyncMock(return_value=False))
    upload_file = AsyncMock(return_value="s3://ecolens/staging/x.duckdb")
    monkeypatch.setattr(object_storage, "upload_file", upload_file)

    key = await upload_staged_file(path, "bom_observations", "run-6")

    assert key == "staging/bom_observations-run-6.duckdb"
    upload_file.assert_awaited_once()
    call_path, call_key = upload_file.call_args.args
    # The uploaded file is a throwaway per-run snapshot, not the shared
    # file itself -- different path, and it shouldn't survive the call.
    assert str(call_path) != path
    assert not call_path.exists()
    assert call_key == "staging/bom_observations-run-6.duckdb"


async def test_upload_staged_file_snapshot_contains_only_that_runs_rows(monkeypatch):
    df1 = pd.DataFrame({"a": [1]})
    df2 = pd.DataFrame({"a": [2]})
    path, _ = stage_dataframe(df1, "bom_observations", "run-7")
    stage_dataframe(df2, "bom_observations", "run-7b")

    monkeypatch.setattr(object_storage, "object_exists", AsyncMock(return_value=False))

    captured_path = {}

    async def fake_upload_file(local_path, key, bucket=None):
        # Read it back before the caller deletes it, to prove the
        # snapshot really only has run-7's row (not run-7b's too).
        import duckdb

        con = duckdb.connect(str(local_path), read_only=True)
        try:
            captured_path["rows"] = (
                con.execute("SELECT * FROM landed").df()["a"].tolist()
            )
        finally:
            con.close()
        return f"s3://ecolens/{key}"

    monkeypatch.setattr(object_storage, "upload_file", fake_upload_file)

    await upload_staged_file(path, "bom_observations", "run-7")

    assert captured_path["rows"] == [1]


async def test_upload_staged_file_skips_upload_when_key_already_exists(monkeypatch):
    """`services/ingestion/TODO.md` Phase 2's "Verify Idempotency" item --
    a redelivered/retried publish shouldn't pay for a redundant upload."""
    df = pd.DataFrame({"a": [1]})
    path, _ = stage_dataframe(df, "bom_observations", "run-8")

    monkeypatch.setattr(object_storage, "object_exists", AsyncMock(return_value=True))
    upload_file = AsyncMock()
    monkeypatch.setattr(object_storage, "upload_file", upload_file)

    key = await upload_staged_file(path, "bom_observations", "run-8")

    assert key == "staging/bom_observations-run-8.duckdb"
    upload_file.assert_not_awaited()
