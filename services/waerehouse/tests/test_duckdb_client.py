import duckdb
import pandas as pd
import pytest

from app.core.config import get_settings
from app.db.duckdb_client import read_run, staging_path


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
