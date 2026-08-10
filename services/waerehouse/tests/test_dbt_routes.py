from datetime import UTC, datetime

from app.api.v1 import deps
from app.dbt import scheduler as dbt_scheduler


class _FakeMappingsResult:
    def __init__(self, row: dict | None = None, rows: list[dict] | None = None):
        self._row = row
        self._rows = rows if rows is not None else []

    def first(self):
        return self._row

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(
        self,
        row: dict | None = None,
        rows: list[dict] | None = None,
        first_row: object = None,
    ):
        self._row = row
        self._rows = rows
        self._first_row = first_row

    def mappings(self):
        return _FakeMappingsResult(row=self._row, rows=self._rows)

    def first(self):
        """Simulates `INSERT ... RETURNING id`'s `.first()` -- a truthy
        row when the lock was acquired, `None` when the `WHERE NOT
        EXISTS` clause suppressed the insert."""
        return self._first_row


class _FakeDb:
    def __init__(
        self,
        select_row: dict | None = None,
        select_rows: list[dict] | None = None,
        lock_acquired: bool = True,
    ):
        self.executed: list[tuple[str, dict]] = []
        self.commits = 0
        self._select_row = select_row
        self._select_rows = select_rows if select_rows is not None else []
        self._lock_acquired = lock_acquired

    async def execute(self, query, params=None):
        sql = str(query)
        self.executed.append((sql, params or {}))
        if "INSERT INTO meta._dbt_build_log" in sql:
            return _FakeResult(first_row=("some-id",) if self._lock_acquired else None)
        if "LIMIT :limit" in sql:
            return _FakeResult(rows=self._select_rows)
        return _FakeResult(row=self._select_row)

    async def commit(self):
        self.commits += 1


def _override_db(client, fake_db):
    async def fake_get_db():
        yield fake_db

    client.app.dependency_overrides[deps.get_db] = fake_get_db


class _FakeRedis:
    """Per-test-isolated fake -- `GET /v1/dbt/build/last`/`/build/runs`
    gained real caching 2026-08-11 (`app.core.response_cache`, this
    service's first use of Redis at all). Without this override these
    tests fall through to the real shared local Redis, which both leaks
    a cached response across tests and hits a real network client tied
    to a since-closed event loop between tests (same fix `services/
    forecast-api`'s equivalent cached-endpoint tests already apply)."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


def _override_redis(client):
    client.app.dependency_overrides[deps.get_redis_client] = lambda: _FakeRedis()


async def _fake_publish_triggers(*, triggered_by):
    return []


class TestTriggerDbtBuild:
    def test_successful_build_returns_zero_exit_code(self, client, monkeypatch):
        fake_db = _FakeDb()
        _override_db(client, fake_db)
        monkeypatch.setattr(dbt_scheduler, "run_dbt", lambda subcommand, target: (0, "all good"))
        monkeypatch.setattr(
            dbt_scheduler, "publish_training_triggers_for_build", _fake_publish_triggers
        )

        response = client.post("/v1/dbt/build")

        assert response.status_code == 200
        assert response.json() == {"subcommand": "build", "target": "dev", "exit_code": 0}
        client.app.dependency_overrides.clear()

    def test_successful_build_publishes_training_triggers(self, client, monkeypatch):
        """`TODO.md`'s "Event-Driven Pipeline Trigger" item 1's Event
        Publisher, real work now owned by this service's own build
        route (`api/v1/dbt/routes.py`) since `dbt build` moved here from
        data-pipeline -- a successful build must fire the training-
        trigger publish so forecast-api's `training_worker` picks up an
        incremental fine-tune off of it."""
        fake_db = _FakeDb()
        _override_db(client, fake_db)
        monkeypatch.setattr(dbt_scheduler, "run_dbt", lambda subcommand, target: (0, "all good"))
        calls: list[dict] = []

        async def _fake_publish(*, triggered_by):
            calls.append({"triggered_by": triggered_by})
            return []

        monkeypatch.setattr(dbt_scheduler, "publish_training_triggers_for_build", _fake_publish)

        client.post("/v1/dbt/build")

        assert calls == [{"triggered_by": "dashboard"}]
        client.app.dependency_overrides.clear()

    def test_failed_build_does_not_publish_training_triggers(self, client, monkeypatch):
        fake_db = _FakeDb()
        _override_db(client, fake_db)
        monkeypatch.setattr(
            dbt_scheduler, "run_dbt", lambda subcommand, target: (1, "Compilation Error: boom")
        )
        publish_called = False

        async def _fake_publish(*, triggered_by):
            nonlocal publish_called
            publish_called = True
            return []

        monkeypatch.setattr(dbt_scheduler, "publish_training_triggers_for_build", _fake_publish)

        client.post("/v1/dbt/build")

        assert publish_called is False
        client.app.dependency_overrides.clear()

    def test_logs_a_running_row_then_updates_it_to_success(self, client, monkeypatch):
        fake_db = _FakeDb()
        _override_db(client, fake_db)
        monkeypatch.setattr(dbt_scheduler, "run_dbt", lambda subcommand, target: (0, "ok"))
        monkeypatch.setattr(
            dbt_scheduler, "publish_training_triggers_for_build", _fake_publish_triggers
        )

        client.post("/v1/dbt/build")

        insert_sql, insert_params = fake_db.executed[0]
        assert "INSERT INTO meta._dbt_build_log" in insert_sql
        assert insert_params["target"] == "dev"
        assert insert_params["triggered_by"] == "dashboard"

        update_sql, update_params = fake_db.executed[1]
        assert "UPDATE meta._dbt_build_log" in update_sql
        assert update_params["status"] == "success"
        assert update_params["exit_code"] == 0
        assert update_params["error"] is None
        assert fake_db.commits == 2
        client.app.dependency_overrides.clear()

    def test_failed_build_logs_failed_status_with_error_output(self, client, monkeypatch):
        fake_db = _FakeDb()
        _override_db(client, fake_db)
        monkeypatch.setattr(
            dbt_scheduler, "run_dbt", lambda subcommand, target: (1, "Compilation Error: boom")
        )

        response = client.post("/v1/dbt/build")

        assert response.json()["exit_code"] == 1
        update_params = fake_db.executed[1][1]
        assert update_params["status"] == "failed"
        assert update_params["exit_code"] == 1
        assert "Compilation Error" in update_params["error"]
        client.app.dependency_overrides.clear()

    def test_rejects_a_second_concurrent_build_with_409(self, client, monkeypatch):
        fake_db = _FakeDb(lock_acquired=False)
        _override_db(client, fake_db)
        run_dbt_called = False

        def _fake_run_dbt(subcommand, target):
            nonlocal run_dbt_called
            run_dbt_called = True
            return (0, "should never run")

        monkeypatch.setattr(dbt_scheduler, "run_dbt", _fake_run_dbt)

        response = client.post("/v1/dbt/build")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "dbt_build_in_progress"
        # The lock check must short-circuit before ever invoking dbt --
        # a rejected trigger should have zero side effects on a build
        # that's already running.
        assert run_dbt_called is False
        # Only the (suppressed) INSERT attempt -- no UPDATE, since
        # _log_build_finish is never reached for a rejected trigger.
        assert len(fake_db.executed) == 1
        client.app.dependency_overrides.clear()

    def test_lock_acquisition_insert_excludes_stale_running_rows(self, client, monkeypatch):
        """Not a live-DB test (Postgres' own `WHERE NOT EXISTS ...
        started_at > now() - interval` clause enforces the actual
        staleness cutoff) -- just pins that the query text sent to the
        DB includes the staleness guard, so a future edit can't silently
        drop it without a test noticing."""
        fake_db = _FakeDb()
        _override_db(client, fake_db)
        monkeypatch.setattr(dbt_scheduler, "run_dbt", lambda subcommand, target: (0, "ok"))
        monkeypatch.setattr(
            dbt_scheduler, "publish_training_triggers_for_build", _fake_publish_triggers
        )

        client.post("/v1/dbt/build")

        insert_sql, insert_params = fake_db.executed[0]
        assert "WHERE NOT EXISTS" in insert_sql
        assert "status = 'running'" in insert_sql
        assert insert_params["stale_minutes"] == 30
        client.app.dependency_overrides.clear()


class TestLastDbtBuild:
    def test_returns_the_most_recent_row(self, client):
        row = {
            "id": "abc-123",
            "subcommand": "build",
            "target": "dev",
            "trigger": "dashboard_manual",
            "triggered_by": "dashboard",
            "status": "success",
            "started_at": datetime(2026, 8, 8, tzinfo=UTC),
            "finished_at": datetime(2026, 8, 8, 0, 1, tzinfo=UTC),
            "exit_code": 0,
            "error": None,
        }
        fake_db = _FakeDb(select_row=row)
        _override_db(client, fake_db)
        _override_redis(client)

        response = client.get("/v1/dbt/build/last")

        assert response.status_code == 200
        assert response.json()["id"] == "abc-123"
        assert response.json()["status"] == "success"
        client.app.dependency_overrides.clear()

    def test_returns_null_when_no_build_has_ever_run(self, client):
        fake_db = _FakeDb(select_row=None)
        _override_db(client, fake_db)
        _override_redis(client)

        response = client.get("/v1/dbt/build/last")

        assert response.status_code == 200
        assert response.json() is None
        client.app.dependency_overrides.clear()


class TestListDbtBuildRuns:
    def _row(self, **overrides):
        row = {
            "id": "abc-123",
            "subcommand": "build",
            "target": "dev",
            "trigger": "dashboard_manual",
            "triggered_by": "dashboard",
            "status": "success",
            "started_at": datetime(2026, 8, 8, tzinfo=UTC),
            "finished_at": datetime(2026, 8, 8, 0, 1, tzinfo=UTC),
            "exit_code": 0,
            "error": None,
        }
        row.update(overrides)
        return row

    def test_returns_rows_newest_first(self, client):
        rows = [self._row(id="run-2", status="running", finished_at=None), self._row(id="run-1")]
        fake_db = _FakeDb(select_rows=rows)
        _override_db(client, fake_db)
        _override_redis(client)

        response = client.get("/v1/dbt/build/runs")

        assert response.status_code == 200
        body = response.json()
        assert [r["id"] for r in body["data"]] == ["run-2", "run-1"]
        assert body["data"][0]["status"] == "running"
        client.app.dependency_overrides.clear()

    def test_empty_before_any_build_has_ever_run(self, client):
        fake_db = _FakeDb(select_rows=[])
        _override_db(client, fake_db)
        _override_redis(client)

        response = client.get("/v1/dbt/build/runs")

        assert response.status_code == 200
        assert response.json()["data"] == []
        client.app.dependency_overrides.clear()

    def test_limit_query_param_is_forwarded(self, client):
        fake_db = _FakeDb(select_rows=[self._row()])
        _override_db(client, fake_db)
        _override_redis(client)

        response = client.get("/v1/dbt/build/runs?limit=5")

        assert response.status_code == 200
        _, params = fake_db.executed[0]
        assert params["limit"] == 5
        client.app.dependency_overrides.clear()

    def test_requires_no_auth(self, client):
        fake_db = _FakeDb(select_rows=[])
        _override_db(client, fake_db)
        _override_redis(client)

        response = client.get("/v1/dbt/build/runs")

        assert response.status_code != 401
        assert response.status_code != 403
        client.app.dependency_overrides.clear()
