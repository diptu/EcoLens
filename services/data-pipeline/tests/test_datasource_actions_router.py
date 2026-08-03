from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.main import app
from app.api.v1.deps import get_db, get_redis_client
from app.core.config import get_settings
from app.service.datasources import actions as datasources_actions
from app.service.datasources import monitoring as datasources_monitoring
from app.service.pipeline.circuit_breaker import CircuitState

NOW = datetime(2026, 1, 1, tzinfo=UTC)


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
    def __init__(self, config_rows=None, in_flight_sources=(), history_rows=()):
        self.config_rows = {r["id"]: dict(r) for r in (config_rows or [])}
        self.in_flight_sources = set(in_flight_sources)
        self.history_rows = list(history_rows)
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.queries.append((sql, params))

        if "meta.data_sources" in sql:
            ids = set(params.get("ids", []))
            return FakeResult(
                [row for rid, row in self.config_rows.items() if rid in ids]
            )
        if "SELECT 1 FROM meta._ingest_log" in sql:
            in_flight = params["source"] in self.in_flight_sources
            return FakeResult([(1,)] if in_flight else [])
        if sql.strip().startswith("SELECT count(*) FROM meta._ingest_log"):
            return FakeResult([[len(self.history_rows)]])
        if "FROM meta._ingest_log l" in sql and "LEFT JOIN" in sql:
            return FakeResult(list(self.history_rows))
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


class FakeBreaker:
    def __init__(self, state: CircuitState = CircuitState.CLOSED):
        self._state = state

    @property
    def state(self):
        async def _get():
            return self._state

        return _get()


def _seeded_config_rows():
    return [
        {
            "id": id_,
            "enabled": True,
            "cron": None,
            "timezone": None,
            "description": None,
            "auth_type": None,
            "metadata": {},
            "version": 1,
            "created_at": NOW,
            "updated_at": NOW,
        }
        for id_ in ("ds-oe", "ds-aemo-nem", "ds-aemo-wem", "ds-bom", "ds-holidays")
    ]


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
def wired(monkeypatch):
    session = FakeSession(config_rows=_seeded_config_rows())
    redis = FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis
    breaker = FakeBreaker()
    monkeypatch.setattr(datasources_actions, "get_breaker", lambda name: breaker)
    monkeypatch.setattr(datasources_monitoring, "get_breaker", lambda name: breaker)

    async def noop_run_in_background(*args, **kwargs):
        pass

    async def noop_backfill_in_background(*args, **kwargs):
        pass

    monkeypatch.setattr(
        datasources_actions, "run_in_background", noop_run_in_background
    )
    monkeypatch.setattr(
        datasources_actions, "run_backfill_in_background", noop_backfill_in_background
    )
    yield session, redis, breaker
    app.dependency_overrides.clear()


class TestTriggerRun:
    def test_requires_admin_role(self, client, wired):
        response = client.post("/v1/data-sources/ds-bom/run", headers=_auth("analyst"))

        assert response.status_code == 403

    def test_unknown_id_is_404(self, client, wired):
        response = client.post("/v1/data-sources/ds-nonexistent/run", headers=_auth())

        assert response.status_code == 404

    def test_successful_trigger_returns_202_queued(self, client, wired):
        response = client.post(
            "/v1/data-sources/ds-bom/run",
            json={"force": False, "deduplicate": True},
            headers={**_auth(sub="diptu"), "X-Reason": "manual check"},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["source_id"] == "ds-bom"
        assert body["status"] == "queued"
        assert body["triggered_by"] == "diptu"
        assert body["reason"] == "manual check"
        assert body["run_id"].startswith("run-")

    def test_already_running_is_409(self, client, wired):
        session, _, _ = wired
        session.in_flight_sources = {"bom"}

        response = client.post("/v1/data-sources/ds-bom/run", headers=_auth())

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "already_running"

    def test_open_circuit_without_force_is_503(self, client, wired):
        session, _, breaker = wired
        breaker._state = CircuitState.OPEN

        response = client.post(
            "/v1/data-sources/ds-bom/run", json={"force": False}, headers=_auth()
        )

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "circuit_open"

    def test_open_circuit_with_force_is_allowed(self, client, wired):
        session, _, breaker = wired
        breaker._state = CircuitState.OPEN

        response = client.post(
            "/v1/data-sources/ds-bom/run", json={"force": True}, headers=_auth()
        )

        assert response.status_code == 202
        assert response.json()["force"] is True

    def test_idempotency_key_replays_the_cached_response(self, client, wired):
        headers = {**_auth(), "Idempotency-Key": "abc-123"}

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

    def test_requires_admin_role(self, client, wired):
        response = client.post(
            "/v1/data-sources/ds-bom/backfill",
            json=self._body(),
            headers=_auth("analyst"),
        )

        assert response.status_code == 403

    def test_successful_trigger_returns_202_with_chunk_count(self, client, wired):
        response = client.post(
            "/v1/data-sources/ds-bom/backfill", json=self._body(), headers=_auth()
        )

        assert response.status_code == 202
        body = response.json()
        assert body["total_chunks"] == 7  # 7 days / P1D
        assert body["backfill_id"].startswith("bf-")
        assert "progress_url" in body

    def test_start_after_end_is_400(self, client, wired):
        response = client.post(
            "/v1/data-sources/ds-bom/backfill",
            json=self._body(start="2026-01-08T00:00:00Z", end="2026-01-01T00:00:00Z"),
            headers=_auth(),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_range"

    def test_range_over_90_days_is_400(self, client, wired):
        response = client.post(
            "/v1/data-sources/ds-bom/backfill",
            json=self._body(start="2025-01-01T00:00:00Z", end="2026-01-01T00:00:00Z"),
            headers=_auth(),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "range_too_large"

    def test_backfill_in_progress_is_409(self, client, wired):
        session, redis, _ = wired
        redis.store["backfill:lock:ds-bom"] = "bf-existing"

        response = client.post(
            "/v1/data-sources/ds-bom/backfill", json=self._body(), headers=_auth()
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "backfill_in_progress"


class TestSourceHealth:
    def test_requires_auth(self, client, wired):
        response = client.get("/v1/data-sources/ds-bom/health")

        assert response.status_code == 401

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
