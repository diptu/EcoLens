from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.core.config import get_settings
from app.service.pipeline import retention
from app.service.pipeline.duckdb_staging import read_staged, stage_dataframe

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


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.executed: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        self.executed.append((str(query), params or {}))
        return _FakeResult(self._rows)


def _fake_get_session(rows):
    @asynccontextmanager
    async def _get_session():
        yield _FakeSession(rows)

    return _get_session


class TestPruneSyncedHistory:
    async def test_returns_empty_dict_when_nothing_is_eligible(self, monkeypatch):
        monkeypatch.setattr(retention, "get_session", _fake_get_session([]))

        result = await retention.prune_synced_history()

        assert result == {}

    async def test_prunes_rows_for_an_eligible_success_run(self, monkeypatch):
        df = pd.DataFrame({"a": [1, 2, 3]})
        stage_dataframe(df, "bom_observations", "run-old")

        monkeypatch.setattr(
            retention, "get_session", _fake_get_session([("run-old", "bom")])
        )

        result = await retention.prune_synced_history(days=7)

        assert result == {"bom": 3}
        path = str(retention.staging_path())
        assert read_staged(path, "bom_observations", "run-old").empty

    async def test_leaves_other_runs_rows_untouched(self, monkeypatch):
        df_old = pd.DataFrame({"a": [1]})
        df_kept = pd.DataFrame({"a": [2]})
        stage_dataframe(df_old, "bom_observations", "run-old")
        stage_dataframe(df_kept, "bom_observations", "run-kept")

        monkeypatch.setattr(
            retention, "get_session", _fake_get_session([("run-old", "bom")])
        )

        await retention.prune_synced_history(days=7)

        path = str(retention.staging_path())
        assert read_staged(path, "bom_observations", "run-kept")["a"].tolist() == [2]

    async def test_skips_a_log_source_with_no_registry_match(self, monkeypatch):
        monkeypatch.setattr(
            retention,
            "get_session",
            _fake_get_session([("run-x", "some_decommissioned_source")]),
        )

        result = await retention.prune_synced_history()

        assert result == {}

    async def test_omits_sources_where_nothing_was_actually_deleted(self, monkeypatch):
        # Eligible per the (mocked) query, but nothing on local disk to
        # delete -- e.g. already pruned by an earlier run.
        monkeypatch.setattr(
            retention, "get_session", _fake_get_session([("run-gone", "bom")])
        )

        result = await retention.prune_synced_history()

        assert result == {}

    async def test_passes_the_cutoff_and_success_filter_to_the_query(self, monkeypatch):
        session = _FakeSession([])

        @asynccontextmanager
        async def _get_session():
            yield session

        monkeypatch.setattr(retention, "get_session", _get_session)

        before = datetime.now(UTC) - timedelta(days=7)
        await retention.prune_synced_history(days=7)
        after = datetime.now(UTC) - timedelta(days=7)

        sql, params = session.executed[0]
        assert "status = 'success'" in sql
        assert "started_at < :cutoff" in sql
        assert before <= params["cutoff"] <= after
