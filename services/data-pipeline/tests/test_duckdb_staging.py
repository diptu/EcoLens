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

    result = read_staged(path)

    assert result.equals(df)


def test_delete_staged_removes_the_file():
    import os

    df = pd.DataFrame({"a": [1]})
    path, _ = stage_dataframe(df, "bom_observations", "run-4")
    assert os.path.exists(path)

    delete_staged(path)

    assert not os.path.exists(path)


def test_delete_staged_is_idempotent_on_a_missing_file():
    # Should not raise -- a retried consumer run may see a file that was
    # already cleaned up by an earlier attempt.
    delete_staged("/nonexistent/path/does-not-exist.duckdb")


def test_different_runs_get_independent_files():
    df1 = pd.DataFrame({"a": [1]})
    df2 = pd.DataFrame({"a": [2, 3]})

    path1, rows1 = stage_dataframe(df1, "bom_observations", "run-a")
    path2, rows2 = stage_dataframe(df2, "bom_observations", "run-b")

    assert path1 != path2
    assert rows1 == 1
    assert rows2 == 2
    assert read_staged(path1)["a"].tolist() == [1]
    assert read_staged(path2)["a"].tolist() == [2, 3]
