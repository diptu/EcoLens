from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.api.v1.datasources import routes as datasources_routes
from app.api.v1.deps import get_db, get_redis_client
from app.core.config import get_settings
from app.main import app
from app.service.datasources import actions as datasources_actions
from app.service.datasources import monitoring as datasources_monitoring
from app.service.datasources import service as datasources_service
from app.service.pipeline.circuit_breaker import CircuitState

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

    def scalar(self):
        return self._rows[0][0] if self._rows else 0


class FakeSession:
    def __init__(self, in_flight_sources=(), history_rows=()):
        self.in_flight_sources = set(in_flight_sources)
        self.history_rows = list(history_rows)
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.queries.append((sql, params))

        if "meta.data_sources" in sql:
            return FakeResult([])
        if "SELECT 1 FROM meta._ingest_log" in sql:
            in_flight = params["source"] in self.in_flight_sources
            return FakeResult([(1,)] if in_flight else [])
        if sql.strip().startswith("SELECT count(*) FROM meta._ingest_log"):
            return FakeResult([[len(self.history_rows)]])
        if "FROM meta._ingest_log l" in sql and "LEFT JOIN" in sql:
            return FakeResult(list(self.history_rows))
        return FakeResult([])


def _token(role: str, sub: str = "diptu") -> str:
    settings = get_settings()
    return jwt.encode(
        {"sub": sub, "role": role},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _auth(role: str = "admin", sub: str = "diptu") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(role, sub)}"}


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


class FakeBreaker:
    def __init__(self, state: CircuitState = CircuitState.CLOSED):
        self._state = state

    @property
    def state(self):
        async def _get():
            return self._state

        return _get()


@pytest.fixture
def wired(monkeypatch):
    session = FakeSession()
    redis = FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis
    breaker = FakeBreaker()
    monkeypatch.setattr(datasources_actions, "get_breaker", lambda name: breaker)
    monkeypatch.setattr(datasources_monitoring, "get_breaker", lambda name: breaker)

    # `get_source_health` calls `fetch_run_rows()`, which opens its own
    # dedicated `get_session()` internally (see that function's own
    # docstring) rather than using the `db` FastAPI already injected
    # above -- `dependency_overrides` only intercepts `Depends(...)`
    # resolution, not this kind of direct module-level call, so it needs
    # patching separately or `/health`'s run-derived fields would silently
    # read from a real database instead of `session`.
    @asynccontextmanager
    async def _fake_get_session():
        yield session

    monkeypatch.setattr(datasources_service, "get_session", _fake_get_session)

    async def noop_run_in_background(*args, **kwargs):
        pass

    async def noop_backfill_in_background(*args, **kwargs):
        pass

    # Real, pre-existing gap found live (2026-08-12, while chasing an
    # unrelated LOG_DB_URL test hang): `app/api/v1/datasources/routes.py`
    # does `from app.service.datasources.actions import run_in_background,
    # run_backfill_in_background` (direct name imports) and passes those
    # bound names straight to `BackgroundTasks.add_task` -- patching
    # `datasources_actions.run_in_background` (the module attribute) never
    # touched what the route actually calls, a real, silent `from x import
    # y` monkeypatch miss. The real functions were firing for true in the
    # background on every `/run`/`/backfill` test all along; harmless
    # (fast, silently erroring against real Postgres/circuit-breaker
    # state) until the log-DB split made one of those real calls slow
    # enough to visibly hang a *later*, unrelated test. Patching the
    # route module's own bound names, not just the source module's, is
    # what actually intercepts the call.
    monkeypatch.setattr(
        datasources_actions, "run_in_background", noop_run_in_background
    )
    monkeypatch.setattr(
        datasources_actions, "run_backfill_in_background", noop_backfill_in_background
    )
    monkeypatch.setattr(
        datasources_routes, "run_in_background", noop_run_in_background
    )
    monkeypatch.setattr(
        datasources_routes, "run_backfill_in_background", noop_backfill_in_background
    )
    yield session, redis, breaker
    app.dependency_overrides.clear()


class TestTriggerRun:
    def test_no_auth_required(self, client, wired):
        """Trigger is deliberately open — no bearer token needed at all."""
        response = client.post("/v1/data-sources/ds-bom/run")

        assert response.status_code == 202

    def test_unknown_id_is_404(self, client, wired):
        response = client.post("/v1/data-sources/ds-nonexistent/run")

        assert response.status_code == 404

    def test_successful_trigger_returns_202_queued(self, client, wired):
        response = client.post(
            "/v1/data-sources/ds-bom/run",
            json={"force": False, "deduplicate": True},
            headers={"X-Reason": "manual check"},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["source_id"] == "ds-bom"
        assert body["status"] == "queued"
        assert body["triggered_by"] == "public"
        assert body["reason"] == "manual check"
        assert body["run_id"].startswith("run-")

    def test_already_running_is_409(self, client, wired):
        session, _, _ = wired
        session.in_flight_sources = {"bom"}

        response = client.post("/v1/data-sources/ds-bom/run")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "already_running"

    def test_open_circuit_without_force_is_503(self, client, wired):
        session, _, breaker = wired
        breaker._state = CircuitState.OPEN

        response = client.post("/v1/data-sources/ds-bom/run", json={"force": False})

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "circuit_open"

    def test_open_circuit_with_force_is_allowed(self, client, wired):
        session, _, breaker = wired
        breaker._state = CircuitState.OPEN

        response = client.post("/v1/data-sources/ds-bom/run", json={"force": True})

        assert response.status_code == 202
        assert response.json()["force"] is True

    def test_idempotency_key_replays_the_cached_response(self, client, wired):
        headers = {"Idempotency-Key": "abc-123"}

        first = client.post("/v1/data-sources/ds-bom/run", headers=headers)
        second = client.post("/v1/data-sources/ds-bom/run", headers=headers)

        assert first.status_code == second.status_code == 202
        assert first.json() == second.json()


class TestTriggerBackfill:
    def _body(self, **overrides):
        body = {
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-08T00:00:00Z",
        }
        body.update(overrides)
        return body

    def test_no_auth_required(self, client, wired):
        """Trigger is deliberately open — no bearer token needed at all."""
        response = client.post("/v1/data-sources/ds-bom/backfill", json=self._body())

        assert response.status_code == 202

    def test_successful_trigger_returns_202_with_chunk_count(self, client, wired):
        response = client.post("/v1/data-sources/ds-bom/backfill", json=self._body())

        assert response.status_code == 202
        body = response.json()
        # 2026-01-01 through 2026-01-08 is 8 real calendar days, inclusive
        # of both ends (`pipeline.backfill.daterange`'s actual execution
        # semantics) -- not the 7-day span's plain duration/chunk-size
        # division, which undercounts real per-day outcomes by 1.
        assert body["total_chunks"] == 8
        assert body["backfill_id"].startswith("bf-")
        assert "progress_url" in body

    def test_start_after_end_is_400(self, client, wired):
        response = client.post(
            "/v1/data-sources/ds-bom/backfill",
            json=self._body(start="2026-01-08T00:00:00Z", end="2026-01-01T00:00:00Z"),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_range"

    def test_start_equal_to_end_is_a_valid_single_day_backfill(self, client, wired):
        response = client.post(
            "/v1/data-sources/ds-bom/backfill",
            json=self._body(start="2026-01-01T00:00:00Z", end="2026-01-01T00:00:00Z"),
        )

        assert response.status_code == 202
        assert response.json()["total_chunks"] == 1

    def test_a_30_day_span_reports_31_real_calendar_day_chunks(self, client, wired):
        """Regression: `total_chunks` used to be `ceil(total_seconds /
        chunk_seconds)`, a plain duration division -- for a 30-day span
        that's 30, but `pipeline.backfill.backfill`'s actual execution
        (`daterange`, inclusive of both `start`'s and `end`'s calendar
        dates) processes 31 real days (Jan 1 through Jan 31 inclusive)."""
        response = client.post(
            "/v1/data-sources/ds-bom/backfill",
            json=self._body(start="2026-01-01T00:00:00Z", end="2026-01-31T00:00:00Z"),
        )

        assert response.status_code == 202
        assert response.json()["total_chunks"] == 31

    def test_range_over_90_days_is_400(self, client, wired):
        response = client.post(
            "/v1/data-sources/ds-bom/backfill",
            json=self._body(start="2025-01-01T00:00:00Z", end="2026-01-01T00:00:00Z"),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "range_too_large"

    def test_backfill_in_progress_is_409(self, client, wired):
        session, redis, _ = wired
        redis.store["backfill:lock:ds-bom"] = "bf-existing"

        response = client.post("/v1/data-sources/ds-bom/backfill", json=self._body())

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "backfill_in_progress"


class TestBackfillStatus:
    def test_unknown_id_is_404(self, client, wired):
        response = client.get("/v1/data-sources/ds-nonexistent/backfill/status")

        assert response.status_code == 404

    def test_not_running_when_no_lock_is_held(self, client, wired):
        response = client.get("/v1/data-sources/ds-bom/backfill/status")

        assert response.status_code == 200
        body = response.json()
        assert body == {"source_id": "ds-bom", "running": False, "trigger": None}

    def test_running_reflects_the_held_lock(self, client, wired):
        # Sets the lock directly rather than going through the trigger
        # endpoint -- TestClient runs BackgroundTasks synchronously as
        # part of the request/response cycle, so by the time `client.
        # post(...)` returns, `run_backfill_in_background`'s own `finally:
        # redis.delete(...)` would already have cleared the lock again.
        _, redis, _ = wired
        redis.store["backfill:lock:ds-bom"] = (
            '{"backfill_id": "bf-123", "source_id": "ds-bom", "status": "queued", '
            '"queued_at": "2026-01-01T00:00:00Z", "start": "2026-01-01T00:00:00Z", '
            '"end": "2026-01-01T00:00:00Z", "chunk": "P1D", "concurrency": 1, '
            '"deduplicate": true, "total_chunks": 1, '
            '"estimated_duration_seconds": 60, "triggered_by": "public", '
            '"progress_url": "/v1/ingestion/runs?backfill_id=bf-123"}'
        )

        response = client.get("/v1/data-sources/ds-bom/backfill/status")

        assert response.status_code == 200
        body = response.json()
        assert body["running"] is True
        assert body["trigger"]["backfill_id"] == "bf-123"


class TestSourceHealth:
    def test_no_token_succeeds(self, client, wired):
        """No auth required for now."""
        response = client.get("/v1/data-sources/ds-bom/health")

        assert response.status_code == 200

    def test_unknown_id_is_404(self, client, wired):
        response = client.get("/v1/data-sources/ds-nonexistent/health", headers=_auth())

        assert response.status_code == 404

    def test_returns_health_shape(self, client, wired):
        response = client.get(
            "/v1/data-sources/ds-bom/health", headers=_auth("analyst")
        )

        assert response.status_code == 200
        body = response.json()
        assert body["source_id"] == "ds-bom"
        assert body["circuit_breaker"]["state"] == "closed"
        assert set(body["errors_by_code_24h"]) == {
            "missing_credentials",
            "timeout",
            "rate_limited",
            "schema_mismatch",
        }


class TestSourceHistory:
    def test_unknown_id_is_404(self, client, wired):
        response = client.get(
            "/v1/data-sources/ds-nonexistent/history", headers=_auth()
        )

        assert response.status_code == 404

    def test_returns_history_rows_with_derived_fields(self, client, wired):
        session, _, _ = wired
        session.history_rows = [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "status": "success",
                "started_at": NOW,
                "finished_at": NOW + timedelta(seconds=1),
                "rows_landed": 12,
                "rows_loaded": 10,
                "error_message": None,
                "triggered_by": "schedule",
                "anomalies_flagged": 2,
            }
        ]

        response = client.get("/v1/data-sources/ds-bom/history", headers=_auth())

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        run = body["data"][0]
        assert run["records_fetched"] == 12
        assert run["records_inserted"] == 10
        assert run["duplicates_skipped"] == 2
        assert run["anomalies_flagged"] == 2
        assert run["trigger"] == "schedule"
        assert run["duration_ms"] == 1000

    def test_limit_out_of_range_is_422(self, client, wired):
        response = client.get(
            "/v1/data-sources/ds-bom/history?limit=1000", headers=_auth()
        )

        assert response.status_code == 422


class _StatusRow:
    def __init__(self, status: str, started_at: datetime):
        self.status = status
        self.started_at = started_at


class _AlreadyInFlightFakeSession:
    """Evaluates `_already_in_flight`'s real SQL semantics (status +
    `started_at` cutoff) against a small fixed set of rows, instead of
    the router-level `FakeSession`'s simple boolean membership check --
    needed here specifically because the behavior under test *is* the
    status/age distinction, not just "does it 409"."""

    def __init__(self, rows: list[_StatusRow]):
        self.rows = rows

    async def execute(self, query, params=None):
        params = params or {}
        cutoff = params["staged_cutoff"]
        matched = any(
            row.status == "running"
            or (row.status == "staged" and row.started_at >= cutoff)
            for row in self.rows
        )
        return FakeResult([(1,)] if matched else [])


class TestAlreadyInFlightStagedStaleness:
    """Real, live-confirmed structural gap (2026-08-07): `status=
    'staged'` only ever resolves to `'success'` via `data-pipeline`'s
    `warehouse_sync` consumer, a *different* service. Without it running
    alongside this one, `staged` rows never resolve — confirmed live,
    `aemo_wem` alone had 497 `staged` rows and only 2 `success`. An
    unbounded in-flight check made `POST .../run` permanently 409 after
    the first successful fetch. `running` still has no bound
    (deliberately); `staged` now does.

    Scoped `anyio` marker on this class only (not module-wide) — every
    other test in this file is synchronous (`TestClient`-driven); these
    call `_already_in_flight` directly and need a real event loop.
    """

    pytestmark = pytest.mark.anyio

    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    async def test_a_running_row_blocks_regardless_of_age(self):
        session = _AlreadyInFlightFakeSession(
            [_StatusRow("running", NOW - timedelta(days=3))]
        )

        assert await datasources_actions._already_in_flight(session, "bom") is True

    async def test_a_recent_staged_row_blocks(self):
        session = _AlreadyInFlightFakeSession(
            [_StatusRow("staged", NOW - timedelta(minutes=5))]
        )

        assert await datasources_actions._already_in_flight(session, "bom") is True

    async def test_a_stale_staged_row_does_not_block(self):
        session = _AlreadyInFlightFakeSession(
            [_StatusRow("staged", NOW - timedelta(hours=2))]
        )

        assert await datasources_actions._already_in_flight(session, "bom") is False

    async def test_success_and_failed_rows_never_block(self):
        session = _AlreadyInFlightFakeSession(
            [
                _StatusRow("success", NOW),
                _StatusRow("failed", NOW),
            ]
        )

        assert await datasources_actions._already_in_flight(session, "bom") is False

    async def test_no_rows_at_all_does_not_block(self):
        session = _AlreadyInFlightFakeSession([])

        assert await datasources_actions._already_in_flight(session, "bom") is False
