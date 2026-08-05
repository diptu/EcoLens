from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from app.retention import pruning

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class _FakeSession:
    def __init__(self, rowcounts):
        self._rowcounts = rowcounts
        self.executed: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        self.executed.append((sql, params or {}))
        for table, rowcount in self._rowcounts.items():
            if table in sql:
                return _FakeResult(rowcount)
        return _FakeResult(0)


def _fake_get_session(rowcounts):
    session = _FakeSession(rowcounts)

    @asynccontextmanager
    async def _get_session():
        yield session

    return _get_session, session


async def test_returns_empty_dict_when_nothing_is_eligible(monkeypatch):
    get_session, _ = _fake_get_session({})
    monkeypatch.setattr(pruning, "get_session", get_session)

    result = await pruning.prune_raw_tables()

    assert result == {}


async def test_prunes_every_table_with_eligible_rows(monkeypatch):
    get_session, session = _fake_get_session(
        {
            "aemo_nem_dispatch": 120,
            "aemo_wem_dispatch": 0,
            "bom_observations": 45,
            "openelectricity_mix": 0,
        }
    )
    monkeypatch.setattr(pruning, "get_session", get_session)

    result = await pruning.prune_raw_tables(days=60)

    assert result == {"aemo_nem_dispatch": 120, "bom_observations": 45}
    assert len(session.executed) == 4


async def test_never_touches_aemo_holidays():
    assert "aemo_holidays" not in pruning._PRUNABLE_TABLES


async def test_uses_the_ts_column_and_the_given_day_window(monkeypatch):
    get_session, session = _fake_get_session({"aemo_nem_dispatch": 5})
    monkeypatch.setattr(pruning, "get_session", get_session)

    before = datetime.now(UTC) - timedelta(days=30)
    await pruning.prune_raw_tables(days=30)
    after = datetime.now(UTC) - timedelta(days=30)

    sql, params = session.executed[0]
    assert 'DELETE FROM raw."aemo_nem_dispatch"' in sql
    assert '"ts" < :cutoff' in sql
    assert before <= params["cutoff"] <= after


async def test_defaults_to_settings_retention_days(monkeypatch):
    get_session, session = _fake_get_session({"aemo_nem_dispatch": 1})
    monkeypatch.setattr(pruning, "get_session", get_session)

    settings = pruning.get_settings()
    before = datetime.now(UTC) - timedelta(days=settings.retention_days)
    await pruning.prune_raw_tables()
    after = datetime.now(UTC) - timedelta(days=settings.retention_days)

    _, params = session.executed[0]
    assert before <= params["cutoff"] <= after
