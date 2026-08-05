from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.service.pipeline import dbt_build_log

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeSession:
    def __init__(self, rows=None):
        self.queries: list[tuple[str, dict]] = []
        self._rows = rows or []

    async def execute(self, query, params=None):
        self.queries.append((str(query), params or {}))
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def fake_session(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(dbt_build_log, "get_session", lambda: _FakeSessionCtx(session))
    return session


async def test_log_start_inserts_a_running_row(fake_session):
    log_id = await dbt_build_log.log_dbt_build_start(
        subcommand="build", target="prod", trigger="backfill_auto", triggered_by="test"
    )

    assert log_id is not None
    query, params = fake_session.queries[0]
    assert "INSERT INTO meta._dbt_build_log" in query
    assert params["subcommand"] == "build"
    assert params["target"] == "prod"
    assert params["trigger"] == "backfill_auto"
    assert params["triggered_by"] == "test"
    assert params["id"] == str(log_id)


async def test_log_finish_updates_status_and_truncates_long_errors(fake_session):
    await dbt_build_log.log_dbt_build_finish(
        "some-id", status="failed", exit_code=1, error="x" * 1000
    )

    query, params = fake_session.queries[0]
    assert "UPDATE meta._dbt_build_log" in query
    assert params["status"] == "failed"
    assert params["exit_code"] == 1
    assert len(params["error"]) == 500


async def test_log_finish_with_no_error_stores_none(fake_session):
    await dbt_build_log.log_dbt_build_finish("some-id", status="success", exit_code=0)

    _, params = fake_session.queries[0]
    assert params["error"] is None


async def test_list_dbt_build_runs_maps_rows(fake_session):
    fake_session._rows = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "subcommand": "build",
            "target": "prod",
            "trigger": "backfill_auto",
            "triggered_by": "backfill:ds-aemo-nem",
            "status": "success",
            "started_at": datetime(2026, 1, 1, tzinfo=UTC),
            "finished_at": datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
            "exit_code": 0,
            "error": None,
        }
    ]

    runs = await dbt_build_log.list_dbt_build_runs(fake_session, limit=20)

    assert len(runs) == 1
    assert runs[0].id == "11111111-1111-1111-1111-111111111111"
    assert runs[0].status == "success"
    assert runs[0].trigger == "backfill_auto"
    assert runs[0].triggered_by == "backfill:ds-aemo-nem"
