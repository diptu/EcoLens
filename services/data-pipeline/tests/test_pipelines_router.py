from __future__ import annotations

from datetime import UTC, datetime

import jwt
import pytest

from app.main import app
from app.api.v1.deps import get_db, get_redis_client
from app.core.config import get_settings
from app.service import pipelines as pipelines_service
from app.service.pipeline.dbt_build import DbtBuildLockTimeout

NOW = datetime.now(UTC)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def one(self):
        return self._rows[0]

    def scalar(self):
        return self._rows[0][0] if self._rows else 0


class FakeSession:
    """Returns empty/zero for everything by default -- these tests exercise
    auth gating and 404/409/idempotency error paths, not the query
    results themselves (verified separately against a real Postgres
    instance -- see the session summary for that verification run)."""

    def __init__(self, pipeline_rows=None, run_row=None):
        self.pipeline_rows = pipeline_rows or []
        self.run_row = run_row
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.queries.append((sql, params))

        if "FROM meta.pipelines" in sql and sql.strip().startswith("SELECT"):
            return FakeResult(self.pipeline_rows)
        if "FROM meta.data_sources" in sql:
            return FakeResult([])
        if sql.strip().startswith("UPDATE meta.pipelines"):
            return FakeResult(
                [
                    {
                        "paused_at": NOW,
                        "paused_by": params.get("paused_by"),
                        "reason": params.get("reason"),
                    }
                ]
            )
        if "l.hostname" in sql and "l.id = :id" in sql:
            return FakeResult([self.run_row] if self.run_row else [])
        if "l.hostname" in sql:
            return FakeResult([])
        if "FILTER (WHERE started_at" in sql:
            return FakeResult([{"failed_24h": 0, "failed_7d": 0}])
        if "min(finished_at) AS oldest" in sql:
            return FakeResult([{"cnt": 0, "oldest": None}])
        if sql.strip().startswith("SELECT count(*)"):
            return FakeResult([[0]])
        return FakeResult([])


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)

    async def scan_iter(self, match=None):
        prefix = match.rstrip("*") if match else ""
        for key in list(self.store):
            if key.startswith(prefix):
                yield key


def _token(role: str, sub: str = "diptu") -> str:
    settings = get_settings()
    return jwt.encode(
        {"sub": sub, "role": role},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _auth(role: str = "admin", sub: str = "diptu") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(role, sub)}"}


@pytest.fixture
def wired():
    session = FakeSession()
    redis = FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis
    yield session, redis
    app.dependency_overrides.clear()


class TestListPipelines:
    def test_requires_auth(self, client, wired):
        response = client.get("/v1/ingestion/pipelines")

        assert response.status_code == 401

    def test_returns_all_6_pipelines(self, client, wired):
        response = client.get("/v1/ingestion/pipelines", headers=_auth("analyst"))

        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total"] == 6
        ids = {p["id"] for p in body["data"]}
        assert ids == {
            "pipe-oe",
            "pipe-aemo-nem",
            "pipe-aemo-wem",
            "pipe-bom",
            "pipe-holidays",
            "pipe-dbt-warehouse",
        }
        dbt = next(p for p in body["data"] if p["id"] == "pipe-dbt-warehouse")
        assert dbt["stage"] == "transform"
        assert dbt["source_id"] is None
        assert dbt["depends_on"] == [
            "pipe-oe",
            "pipe-aemo-nem",
            "pipe-aemo-wem",
            "pipe-bom",
            "pipe-holidays",
        ]


class TestListPipelinesPublic:
    def test_does_not_require_auth(self, client, wired):
        response = client.get("/v1/ingestion/public/pipelines")

        assert response.status_code == 200

    def test_returns_all_6_pipelines(self, client, wired):
        response = client.get("/v1/ingestion/public/pipelines")

        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total"] == 6
        ids = {p["id"] for p in body["data"]}
        assert ids == {
            "pipe-oe",
            "pipe-aemo-nem",
            "pipe-aemo-wem",
            "pipe-bom",
            "pipe-holidays",
            "pipe-dbt-warehouse",
        }

    def test_agrees_with_authenticated_endpoint(self, client, wired):
        authed = client.get("/v1/ingestion/pipelines", headers=_auth("analyst")).json()
        public = client.get("/v1/ingestion/public/pipelines").json()

        assert public == authed


class TestListRuns:
    def test_requires_auth(self, client, wired):
        response = client.get("/v1/ingestion/runs")

        assert response.status_code == 401

    def test_returns_empty_shape(self, client, wired):
        response = client.get("/v1/ingestion/runs", headers=_auth())

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["has_more"] is False


class TestListRunsPublic:
    def test_does_not_require_auth(self, client, wired):
        response = client.get("/v1/ingestion/public/runs")

        assert response.status_code == 200

    def test_returns_empty_shape(self, client, wired):
        response = client.get("/v1/ingestion/public/runs")

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["has_more"] is False


class TestGetRun:
    def test_malformed_id_is_404(self, client, wired):
        response = client.get("/v1/ingestion/runs/not-a-uuid", headers=_auth())

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_unknown_uuid_is_404(self, client, wired):
        response = client.get(
            "/v1/ingestion/runs/11111111-1111-1111-1111-111111111111", headers=_auth()
        )

        assert response.status_code == 404

    def test_found_run_includes_lineage(self, client, wired):
        session, _ = wired
        session.run_row = {
            "id": "11111111-1111-1111-1111-111111111111",
            "source": "bom",
            "status": "success",
            "started_at": NOW,
            "finished_at": NOW,
            "rows_landed": 10,
            "rows_loaded": 10,
            "error_message": None,
            "triggered_by": "schedule",
            "hostname": "runner-1",
            "circuit_breaker_state": "closed",
            "window_start": None,
            "window_end": None,
            "anomalies_flagged": 0,
        }

        response = client.get(
            "/v1/ingestion/runs/11111111-1111-1111-1111-111111111111", headers=_auth()
        )

        assert response.status_code == 200
        body = response.json()
        assert body["pipeline_id"] == "pipe-bom"
        assert body["lineage"]["output_datasets"] == ["raw.bom_observations"]
        assert body["retry_chain"] == []
        assert body["logs_url"] is None


class TestFailedAndRetryQueue:
    def test_failed_requires_auth(self, client, wired):
        response = client.get("/v1/ingestion/failed")

        assert response.status_code == 401

    def test_failed_returns_empty_shape(self, client, wired):
        response = client.get("/v1/ingestion/failed", headers=_auth())

        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_retry_queue_returns_empty_shape(self, client, wired):
        response = client.get("/v1/ingestion/retry-queue", headers=_auth())

        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["queue_size"] == 0
        assert body["data"] == []


class TestFailedAndRetryQueuePublic:
    def test_failed_does_not_require_auth(self, client, wired):
        response = client.get("/v1/ingestion/public/failed")

        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_retry_queue_does_not_require_auth(self, client, wired):
        response = client.get("/v1/ingestion/public/retry-queue")

        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["queue_size"] == 0
        assert body["data"] == []


class TestScheduler:
    def test_requires_auth(self, client, wired):
        response = client.get("/v1/ingestion/scheduler")

        assert response.status_code == 401

    def test_all_6_pipelines_are_upcoming_when_nothing_is_paused(self, client, wired):
        response = client.get("/v1/ingestion/scheduler", headers=_auth("analyst"))

        assert response.status_code == 200
        body = response.json()
        assert body["scheduler"]["status"] == "healthy"
        assert len(body["upcoming_runs"]) == 6


class TestSchedulerPublic:
    def test_does_not_require_auth(self, client, wired):
        response = client.get("/v1/ingestion/public/scheduler")

        assert response.status_code == 200
        body = response.json()
        assert body["scheduler"]["status"] == "healthy"
        assert body["scheduler"]["prefect_version"] is None
        assert len(body["upcoming_runs"]) == 6


class TestPauseResume:
    def test_pause_requires_admin_role(self, client, wired):
        response = client.post("/v1/ingestion/pipe-bom/pause", headers=_auth("analyst"))

        assert response.status_code == 403

    def test_resume_requires_admin_role(self, client, wired):
        response = client.post(
            "/v1/ingestion/pipe-bom/resume", headers=_auth("analyst")
        )

        assert response.status_code == 403

    def test_pause_unknown_pipeline_is_404(self, client, wired):
        response = client.post("/v1/ingestion/pipe-nonexistent/pause", headers=_auth())

        assert response.status_code == 404

    def test_resume_unknown_pipeline_is_404(self, client, wired):
        response = client.post("/v1/ingestion/pipe-nonexistent/resume", headers=_auth())

        assert response.status_code == 404

    def test_cannot_pause_dbt_pipeline(self, client, wired):
        response = client.post(
            "/v1/ingestion/pipe-dbt-warehouse/pause", headers=_auth()
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "cannot_pause_dbt"

    def test_pause_then_response_shape(self, client, wired):
        response = client.post(
            "/v1/ingestion/pipe-bom/pause",
            json={"reason": "vendor outage"},
            headers=_auth(),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == "pipe-bom"
        assert body["status"] == "paused"
        assert body["reason"] == "vendor outage"
        assert body["next_scheduled_run"] is None

    def test_pause_already_paused_is_idempotent_no_op(self, client, wired):
        session, _ = wired
        session.pipeline_rows = [
            {
                "id": "pipe-bom",
                "status": "paused",
                "paused_at": NOW,
                "paused_by": "someone-else",
                "reason": "already paused",
            }
        ]

        response = client.post(
            "/v1/ingestion/pipe-bom/pause",
            json={"reason": "new reason"},
            headers=_auth(),
        )

        assert response.status_code == 200
        body = response.json()
        # No-op: the existing paused_by/reason survive, not the new request's.
        assert body["paused_by"] == "someone-else"
        assert body["reason"] == "already paused"
        update_calls = [q for q, _ in session.queries if q.strip().startswith("UPDATE")]
        assert update_calls == []

    def test_resume_active_pipeline_is_idempotent_no_op(self, client, wired):
        response = client.post("/v1/ingestion/pipe-bom/resume", headers=_auth())

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "active"
        assert body["next_scheduled_run"] is not None

    def test_resume_paused_pipeline_updates_and_computes_next_run(self, client, wired):
        session, _ = wired
        session.pipeline_rows = [
            {
                "id": "pipe-bom",
                "status": "paused",
                "paused_at": NOW,
                "paused_by": "diptu",
                "reason": "testing",
            }
        ]

        response = client.post("/v1/ingestion/pipe-bom/resume", headers=_auth())

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "active"
        assert body["next_scheduled_run"] is not None
        update_calls = [q for q, _ in session.queries if q.strip().startswith("UPDATE")]
        assert len(update_calls) == 1


class TestTriggerDbtWarehouseBuild:
    """`POST /v1/ingestion/dbt-warehouse/build` -- the manual escape hatch
    for TODO.md's backfill-section gap (a dashboard-triggered backfill
    never refreshed `raw_marts.*` on its own). Deliberately open, unlike
    `/v1/dbt/{subcommand}` -- see `pipelines.trigger_dbt_warehouse_build`'s
    docstring for why."""

    def test_no_auth_required(self, client, wired, monkeypatch):
        async def fake_locked(redis, *, trigger, triggered_by, max_wait_seconds=0):
            return 0

        monkeypatch.setattr(pipelines_service, "run_dbt_build_locked", fake_locked)

        response = client.post("/v1/ingestion/dbt-warehouse/build")

        assert response.status_code == 200
        body = response.json()
        assert body == {"subcommand": "build", "target": "prod", "exit_code": 0}

    def test_build_failure_is_a_500(self, client, wired, monkeypatch):
        async def fake_locked(redis, *, trigger, triggered_by, max_wait_seconds=0):
            return 1

        monkeypatch.setattr(pipelines_service, "run_dbt_build_locked", fake_locked)

        response = client.post("/v1/ingestion/dbt-warehouse/build")

        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal"

    def test_concurrent_build_fails_fast_with_409(self, client, wired, monkeypatch):
        async def fake_locked(redis, *, trigger, triggered_by, max_wait_seconds=0):
            assert max_wait_seconds == 0  # fails fast, doesn't hold the request open
            raise DbtBuildLockTimeout("another build is still running")

        monkeypatch.setattr(pipelines_service, "run_dbt_build_locked", fake_locked)

        response = client.post("/v1/ingestion/dbt-warehouse/build")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "dbt_build_in_progress"


class _RedactionResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]

    def scalar(self):
        return self._rows[0][0] if self._rows else 0


class _RedactionSession:
    """Returns one failed/sync_failed `meta._ingest_log` row carrying a
    secret-looking `error_message`, for both `list_failed`'s and
    `list_retry_queue`'s row query -- purpose-built for
    `TestPublicErrorRedaction` since the shared `FakeSession` above
    always returns empty for these (it exists for the auth/shape tests,
    not row content)."""

    def __init__(self, message: str):
        self.message = message

    async def execute(self, query, params=None):
        sql = str(query)
        if "l.hostname" in sql and "l.id = :id" not in sql:
            return _RedactionResult(
                [
                    {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "source": "oe",
                        "status": "failed",
                        "started_at": NOW,
                        "finished_at": NOW,
                        "rows_landed": None,
                        "rows_loaded": None,
                        "error_message": self.message,
                        "triggered_by": "schedule",
                        "hostname": "runner-1",
                        "circuit_breaker_state": "closed",
                        "window_start": None,
                        "window_end": None,
                        "anomalies_flagged": 0,
                    }
                ]
            )
        if "FILTER (WHERE started_at" in sql:
            return _RedactionResult([{"failed_24h": 1, "failed_7d": 1}])
        if "min(finished_at) AS oldest" in sql:
            return _RedactionResult([{"cnt": 1, "oldest": NOW}])
        if sql.strip().startswith("SELECT count(*)"):
            return _RedactionResult([[1]])
        return _RedactionResult([])


_SECRET_MESSAGE = (
    "HTTP 500 for url 'https://api.openelectricity.org.au/data?api_key=SECRET123ABC'"
)


class TestPublicErrorRedaction:
    def test_failed_message_is_redacted(self, client):
        app.dependency_overrides[get_db] = lambda: _RedactionSession(_SECRET_MESSAGE)
        app.dependency_overrides[get_redis_client] = lambda: FakeRedis()
        try:
            response = client.get("/v1/ingestion/public/failed")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        message = response.json()["data"][0]["error"]["message"]
        assert "SECRET123ABC" not in message
        assert "[redacted]" in message

    def test_retry_queue_message_is_redacted(self, client):
        app.dependency_overrides[get_db] = lambda: _RedactionSession(_SECRET_MESSAGE)
        app.dependency_overrides[get_redis_client] = lambda: FakeRedis()
        try:
            response = client.get("/v1/ingestion/public/retry-queue")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        message = response.json()["data"][0]["last_error"]["message"]
        assert "SECRET123ABC" not in message
        assert "[redacted]" in message

    def test_authenticated_failed_endpoint_is_not_redacted(self, client):
        """Confirms redaction is public-only -- an authenticated
        admin/analyst still sees the real message for actual debugging."""
        app.dependency_overrides[get_db] = lambda: _RedactionSession(_SECRET_MESSAGE)
        app.dependency_overrides[get_redis_client] = lambda: FakeRedis()
        try:
            response = client.get("/v1/ingestion/failed", headers=_auth())
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert "SECRET123ABC" in response.json()["data"][0]["error"]["message"]
