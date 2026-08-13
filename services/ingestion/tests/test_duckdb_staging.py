import os
from pathlib import Path
from unittest.mock import AsyncMock

import duckdb
import pandas as pd
import pytest

from app.core.config import get_settings
from app.service import object_storage
from app.service.pipeline import duckdb_staging
from app.service.pipeline.duckdb_staging import (
    delete_staged,
    merge_staging_file,
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


class TestMergeStagingFile:
    """`merge_staging_file` -- reconciling a separate per-source scratch
    file (e.g. from a parallel backfill run with its own
    `DUCKDB_STAGING_DIR`, to sidestep the canonical file's single-writer
    lock) back into the canonical shared staging file."""

    def test_merges_rows_from_a_separate_staging_file(self, tmp_path, monkeypatch):
        scratch_dir = tmp_path / "scratch"
        monkeypatch.setenv("DUCKDB_STAGING_DIR", str(scratch_dir))
        get_settings.cache_clear()
        scratch_path, rows = stage_dataframe(
            pd.DataFrame({"a": [1, 2, 3]}), "bom_observations", "run-scratch"
        )
        assert rows == 3

        # Back to the canonical (fixture) dir before merging.
        monkeypatch.setenv("DUCKDB_STAGING_DIR", str(tmp_path))
        get_settings.cache_clear()

        merged = merge_staging_file(Path(scratch_path), "bom_observations")

        assert merged == 3
        canonical_path = str(tmp_path / "landed.duckdb")
        result = read_staged(canonical_path, "bom_observations", "run-scratch")
        assert result["a"].tolist() == [1, 2, 3]

    def test_appends_into_an_existing_canonical_table(self, tmp_path, monkeypatch):
        stage_dataframe(pd.DataFrame({"a": [1]}), "bom_observations", "run-existing")

        scratch_dir = tmp_path / "scratch"
        monkeypatch.setenv("DUCKDB_STAGING_DIR", str(scratch_dir))
        get_settings.cache_clear()
        scratch_path, _ = stage_dataframe(
            pd.DataFrame({"a": [2]}), "bom_observations", "run-scratch"
        )

        monkeypatch.setenv("DUCKDB_STAGING_DIR", str(tmp_path))
        get_settings.cache_clear()

        merged = merge_staging_file(Path(scratch_path), "bom_observations")

        assert merged == 1
        canonical_path = str(tmp_path / "landed.duckdb")
        existing = read_staged(canonical_path, "bom_observations", "run-existing")
        scratch_rows = read_staged(canonical_path, "bom_observations", "run-scratch")
        assert existing["a"].tolist() == [1]
        assert scratch_rows["a"].tolist() == [2]

    def test_missing_source_file_is_a_noop(self, tmp_path):
        merged = merge_staging_file(
            tmp_path / "does-not-exist.duckdb", "bom_observations"
        )

        assert merged == 0

    def test_source_file_without_the_table_is_a_noop(self, tmp_path, monkeypatch):
        scratch_dir = tmp_path / "scratch"
        monkeypatch.setenv("DUCKDB_STAGING_DIR", str(scratch_dir))
        get_settings.cache_clear()
        scratch_path, _ = stage_dataframe(
            pd.DataFrame({"demand_mw": [1]}), "aemo_nem_dispatch", "run-scratch"
        )

        monkeypatch.setenv("DUCKDB_STAGING_DIR", str(tmp_path))
        get_settings.cache_clear()

        merged = merge_staging_file(Path(scratch_path), "bom_observations")

        assert merged == 0


class TestConnectRwWithRetry:
    """`_connect_rw_with_retry` -- added 2026-08-07 after a real,
    live-confirmed failure: `ingest_all_sources_task`'s parallel
    `celery.group` fan-out means multiple sources can finish fetching at
    close to the same moment and race for DuckDB's single read-write
    lock on the shared staging file. Before this, the loser got a hard
    `duckdb.IOException` and the whole ingest run failed -- confirmed
    live against real concurrent Celery workers (`aemo-nem`/`bom` both
    failed with "Conflicting lock is held" in the same 30-min tick)."""

    def test_retries_and_succeeds_after_transient_lock_contention(
        self, tmp_path, monkeypatch
    ):
        path = tmp_path / "landed.duckdb"
        real_connect = duckdb.connect
        calls = {"n": 0}

        def flaky_connect(target, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise duckdb.IOException(
                    f'IO Error: Could not set lock on file "{target}": '
                    "Conflicting lock is held in some other process"
                )
            return real_connect(target, *args, **kwargs)

        monkeypatch.setattr(duckdb, "connect", flaky_connect)
        monkeypatch.setattr(duckdb_staging.time, "sleep", lambda _: None)

        con = duckdb_staging._connect_rw_with_retry(path)
        con.close()

        assert calls["n"] == 3

    def test_gives_up_after_max_attempts_still_locked(self, tmp_path, monkeypatch):
        path = tmp_path / "landed.duckdb"

        def always_locked(target, *args, **kwargs):
            raise duckdb.IOException(
                f'IO Error: Could not set lock on file "{target}": '
                "Conflicting lock is held forever"
            )

        monkeypatch.setattr(duckdb, "connect", always_locked)
        monkeypatch.setattr(duckdb_staging.time, "sleep", lambda _: None)

        with pytest.raises(duckdb.IOException, match="Conflicting lock"):
            duckdb_staging._connect_rw_with_retry(path)

    def test_a_different_ioexception_is_not_retried(self, tmp_path, monkeypatch):
        calls = {"n": 0}

        def not_a_lock_error(target, *args, **kwargs):
            calls["n"] += 1
            raise duckdb.IOException("IO Error: disk full")

        monkeypatch.setattr(duckdb, "connect", not_a_lock_error)

        with pytest.raises(duckdb.IOException, match="disk full"):
            duckdb_staging._connect_rw_with_retry(tmp_path / "landed.duckdb")

        assert calls["n"] == 1

    def test_concurrent_stage_dataframe_calls_do_not_lose_either_write(
        self, tmp_path, monkeypatch
    ):
        """The real-world scenario, without needing two OS processes:
        thread B's write is deliberately made to look like it's mid-lock
        while thread A holds the connection, by monkeypatching `connect`
        to raise "Conflicting lock" exactly once for the second caller
        -- confirming the retry actually recovers a real write, not just
        a mocked-away connection object."""
        monkeypatch.setenv("DUCKDB_STAGING_DIR", str(tmp_path))
        get_settings.cache_clear()

        df_a = pd.DataFrame({"demand_mw": [1, 2]})
        df_b = pd.DataFrame({"demand_mw": [3, 4]})

        real_connect = duckdb.connect
        state = {"first_call_done": False}

        def contend_once(target, *args, **kwargs):
            if not state["first_call_done"]:
                state["first_call_done"] = True
                return real_connect(target, *args, **kwargs)
            state["first_call_done"] = "retried"
            raise duckdb.IOException(
                f'IO Error: Could not set lock on file "{target}": '
                "Conflicting lock is held in some other process"
            )

        # Only the *second* stage_dataframe call should ever hit the
        # simulated contention -- the first proceeds normally, occupies
        # and releases the lock (this module holds it only for the
        # duration of one call, per its own module docstring), then the
        # second's first attempt is rejected and its retry succeeds for
        # real against the now-free file.
        path, rows_a = stage_dataframe(df_a, "aemo_nem_dispatch", "run-a")
        assert rows_a == 2

        monkeypatch.setattr(duckdb, "connect", contend_once)
        monkeypatch.setattr(duckdb_staging.time, "sleep", lambda _: None)
        state["first_call_done"] = False  # arm contention for this call only

        _, rows_b = stage_dataframe(df_b, "aemo_nem_dispatch", "run-b")
        assert rows_b == 2

        monkeypatch.setattr(duckdb, "connect", real_connect)
        con = duckdb.connect(path, read_only=True)
        try:
            total = con.execute("SELECT count(*) FROM aemo_nem_dispatch").fetchone()
            assert total is not None
            assert total[0] == 4
        finally:
            con.close()
