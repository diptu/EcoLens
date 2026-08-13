from datetime import UTC, datetime, timedelta

import pytest

from app.dbt import scheduler as dbt_scheduler

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeResult:
    def __init__(self, row=None, first_row=None):
        self._row = row
        self._first_row = first_row

    def first(self):
        return self._first_row if self._first_row is not None else self._row


class _FakeDb:
    def __init__(self, *, lock_acquired=True, last_build_started_at=None):
        self.executed: list[tuple[str, dict]] = []
        self.commits = 0
        self._lock_acquired = lock_acquired
        self._last_build_started_at = last_build_started_at

    async def execute(self, query, params=None):
        sql = str(query)
        self.executed.append((sql, params or {}))
        if "INSERT INTO meta._dbt_build_log" in sql:
            return _FakeResult(first_row=("some-id",) if self._lock_acquired else None)
        if "SELECT started_at FROM meta._dbt_build_log" in sql:
            row = (self._last_build_started_at,) if self._last_build_started_at else None
            return _FakeResult(first_row=row)
        if "UPDATE meta._dbt_build_log" in sql:
            return _FakeResult()
        raise AssertionError(f"unexpected query: {sql}")

    async def commit(self):
        self.commits += 1


async def _fake_publish(*, triggered_by):
    return []


class TestRunBuild:
    async def test_runs_and_logs_success(self, monkeypatch):
        fake_db = _FakeDb()
        monkeypatch.setattr(
            dbt_scheduler, "run_dbt", lambda subcommand, target: (0, "all good")
        )
        monkeypatch.setattr(
            dbt_scheduler, "publish_training_triggers_for_build", _fake_publish
        )

        outcome = await dbt_scheduler.run_build(
            fake_db, trigger="scheduled", triggered_by="landed_event"
        )

        assert outcome is not None
        exit_code, run_id = outcome
        assert exit_code == 0
        assert isinstance(run_id, str)

        insert_sql, insert_params = fake_db.executed[0]
        assert "INSERT INTO meta._dbt_build_log" in insert_sql
        assert insert_params["trigger"] == "scheduled"
        assert insert_params["triggered_by"] == "landed_event"

        update_sql, update_params = fake_db.executed[1]
        assert "UPDATE meta._dbt_build_log" in update_sql
        assert update_params["status"] == "success"

    async def test_returns_none_when_lock_not_acquired(self, monkeypatch):
        fake_db = _FakeDb(lock_acquired=False)
        run_dbt_called = False

        def fake_run_dbt(subcommand, target):
            nonlocal run_dbt_called
            run_dbt_called = True
            return (0, "should never run")

        monkeypatch.setattr(dbt_scheduler, "run_dbt", fake_run_dbt)

        outcome = await dbt_scheduler.run_build(
            fake_db, trigger="scheduled", triggered_by="landed_event"
        )

        assert outcome is None
        assert run_dbt_called is False

    async def test_does_not_publish_training_triggers_on_failure(self, monkeypatch):
        fake_db = _FakeDb()
        monkeypatch.setattr(
            dbt_scheduler, "run_dbt", lambda subcommand, target: (1, "boom")
        )
        published = False

        async def fake_publish(*, triggered_by):
            nonlocal published
            published = True
            return []

        monkeypatch.setattr(dbt_scheduler, "publish_training_triggers_for_build", fake_publish)

        outcome = await dbt_scheduler.run_build(
            fake_db, trigger="scheduled", triggered_by="landed_event"
        )

        assert outcome is not None
        assert outcome[0] == 1
        assert published is False


class TestTriggerBuildIfDue:
    async def test_triggers_when_no_build_has_ever_run(self, monkeypatch):
        fake_db = _FakeDb(last_build_started_at=None)
        monkeypatch.setattr(dbt_scheduler, "run_dbt", lambda subcommand, target: (0, "ok"))
        monkeypatch.setattr(dbt_scheduler, "publish_training_triggers_for_build", _fake_publish)

        triggered = await dbt_scheduler.trigger_build_if_due(fake_db)

        assert triggered is True

    async def test_triggers_when_the_last_build_is_older_than_the_interval(self, monkeypatch):
        old = datetime.now(UTC) - timedelta(minutes=30)
        fake_db = _FakeDb(last_build_started_at=old)
        monkeypatch.setattr(dbt_scheduler, "run_dbt", lambda subcommand, target: (0, "ok"))
        monkeypatch.setattr(dbt_scheduler, "publish_training_triggers_for_build", _fake_publish)

        triggered = await dbt_scheduler.trigger_build_if_due(fake_db)

        assert triggered is True

    async def test_skips_when_the_last_build_is_recent(self, monkeypatch):
        recent = datetime.now(UTC) - timedelta(minutes=1)
        fake_db = _FakeDb(last_build_started_at=recent)
        run_dbt_called = False

        def fake_run_dbt(subcommand, target):
            nonlocal run_dbt_called
            run_dbt_called = True
            return (0, "should never run")

        monkeypatch.setattr(dbt_scheduler, "run_dbt", fake_run_dbt)

        triggered = await dbt_scheduler.trigger_build_if_due(fake_db)

        assert triggered is False
        assert run_dbt_called is False
        # The debounce check itself queries the last build's timestamp,
        # but must short-circuit before ever trying to acquire the
        # build lock (no INSERT attempt).
        assert all("INSERT" not in sql for sql, _ in fake_db.executed)

    async def test_returns_false_when_another_build_is_already_running(self, monkeypatch):
        fake_db = _FakeDb(last_build_started_at=None, lock_acquired=False)
        run_dbt_called = False

        def fake_run_dbt(subcommand, target):
            nonlocal run_dbt_called
            run_dbt_called = True
            return (0, "should never run")

        monkeypatch.setattr(dbt_scheduler, "run_dbt", fake_run_dbt)

        triggered = await dbt_scheduler.trigger_build_if_due(fake_db)

        assert triggered is False
        assert run_dbt_called is False
