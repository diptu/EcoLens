from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.main import app
from app.api.v1.deps import get_db, get_redis_client
from app.core.config import get_settings
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


CONFIG_ROWS = [
    {
        "id": "ds-oe",
        "enabled": True,
        "version": 1,
        "created_at": NOW - timedelta(days=100),
        "updated_at": NOW - timedelta(days=1),
    },
    {
        "id": "ds-aemo-nem",
        "enabled": True,
        "version": 1,
        "created_at": NOW - timedelta(days=100),
        "updated_at": NOW - timedelta(days=1),
    },
    {
        "id": "ds-aemo-wem",
        "enabled": True,
        "version": 1,
        "created_at": NOW - timedelta(days=100),
        "updated_at": NOW - timedelta(days=1),
    },
    {
        "id": "ds-bom",
        "enabled": True,
        "version": 1,
        "created_at": NOW - timedelta(days=100),
        "updated_at": NOW - timedelta(days=1),
    },
    {
        "id": "ds-holidays",
        "enabled": False,
        "version": 2,
        "created_at": NOW - timedelta(days=100),
        "updated_at": NOW - timedelta(days=1),
    },
]

RUN_ROWS = [
    # openelectricity: all success -> healthy
    {
        "id": "run-oe-1",
        "source": "openelectricity",
        "status": "success",
        "started_at": NOW - timedelta(minutes=5),
        "finished_at": NOW - timedelta(minutes=5) + timedelta(seconds=1),
        "rows_loaded": 12,
        "error_message": None,
    },
    # aemo_nem: most recent run failed -> degraded
    {
        "id": "run-nem-2",
        "source": "aemo_nem",
        "status": "failed",
        "started_at": NOW - timedelta(minutes=15),
        "finished_at": NOW - timedelta(minutes=15) + timedelta(seconds=2),
        "rows_loaded": None,
        "error_message": "upstream timeout",
    },
    {
        "id": "run-nem-1",
        "source": "aemo_nem",
        "status": "success",
        "started_at": NOW - timedelta(minutes=30),
        "finished_at": NOW - timedelta(minutes=30) + timedelta(seconds=1),
        "rows_loaded": 5,
        "error_message": None,
    },
    # aemo_wem: breaker forced open -> failing
    {
        "id": "run-wem-1",
        "source": "aemo_wem",
        "status": "failed",
        "started_at": NOW - timedelta(minutes=10),
        "finished_at": NOW - timedelta(minutes=10) + timedelta(seconds=1),
        "rows_loaded": None,
        "error_message": "circuit open",
    },
    # bom: no runs at all
    # ds-holidays: disabled -> paused regardless of runs
    {
        "id": "run-holidays-1",
        "source": "aemo_holidays",
        "status": "success",
        "started_at": NOW - timedelta(days=200),
        "finished_at": NOW - timedelta(days=200) + timedelta(seconds=1),
        "rows_loaded": 42,
        "error_message": None,
    },
]

BREAKER_STATES = {
    "openelectricity": CircuitState.CLOSED,
    "aemo_nem": CircuitState.CLOSED,
    "aemo_wem": CircuitState.OPEN,
    "bom": CircuitState.CLOSED,
    "aemo_holidays": CircuitState.CLOSED,
}


class FakeSession:
    def __init__(self, config_rows=CONFIG_ROWS, run_rows=RUN_ROWS):
        self.config_rows = config_rows
        self.run_rows = run_rows
        self.queries: list[str] = []

    async def execute(self, query, params):
        sql = str(query)
        self.queries.append(sql)
        if "meta.data_sources" in sql:
            ids = set(params["ids"])
            return FakeResult([r for r in self.config_rows if r["id"] in ids])
        if "meta._ingest_log" in sql:
            sources = set(params["sources"])
            return FakeResult([r for r in self.run_rows if r["source"] in sources])
        raise AssertionError(f"unexpected query: {sql}")


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, key):
        self.get_calls += 1
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.set_calls += 1
        self.store[key] = value


class FakeBreaker:
    def __init__(self, state: CircuitState):
        self._state = state

    @property
    def state(self):
        async def _get():
            return self._state

        return _get()


def _fake_get_breaker(name: str) -> FakeBreaker:
    return FakeBreaker(BREAKER_STATES[name])


def _token(role: str, sub: str = "user-1") -> str:
    settings = get_settings()
    return jwt.encode(
        {"sub": sub, "role": role},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _auth(role: str = "analyst") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(role)}"}


@pytest.fixture(autouse=True)
def _wire_fakes(monkeypatch):
    session = FakeSession()
    redis = FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis
    monkeypatch.setattr(datasources_service, "get_breaker", _fake_get_breaker)
    yield session, redis
    app.dependency_overrides.clear()


class TestNoAuthRequired:
    """No auth required for now (reverted the same day it was added) --
    `GET /v1/data-sources` is open, same as the trigger endpoints."""

    def test_no_token_succeeds(self, client):
        response = client.get("/v1/data-sources")

        assert response.status_code == 200

    def test_garbage_authorization_header_is_ignored(self, client):
        response = client.get(
            "/v1/data-sources", headers={"Authorization": "Bearer garbage"}
        )

        assert response.status_code == 200


class TestListing:
    def test_returns_all_five_catalog_sources_with_computed_health(self, client):
        response = client.get("/v1/data-sources", headers=_auth())

        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total"] == 5
        assert body["meta"]["enabled_count"] == 4
        assert body["meta"]["disabled_count"] == 1
        by_id = {d["id"]: d for d in body["data"]}

        assert by_id["ds-oe"]["health"]["status"] == "healthy"
        assert by_id["ds-aemo-nem"]["health"]["status"] == "degraded"
        assert by_id["ds-aemo-nem"]["health"]["consecutive_failures"] == 1
        assert by_id["ds-aemo-wem"]["health"]["status"] == "failing"
        assert by_id["ds-aemo-wem"]["health"]["circuit_breaker"] == "open"
        assert by_id["ds-bom"]["health"]["status"] == "healthy"
        assert by_id["ds-bom"]["last_run"] is None
        assert by_id["ds-holidays"]["health"]["status"] == "paused"
        assert by_id["ds-holidays"]["schedule"]["enabled"] is False

    def test_last_run_fields_come_from_ingest_log(self, client):
        response = client.get("/v1/data-sources", headers=_auth())

        last_run = next(d for d in response.json()["data"] if d["id"] == "ds-oe")[
            "last_run"
        ]
        assert last_run["id"] == "run-oe-1"
        assert last_run["status"] == "success"
        assert last_run["records_inserted"] == 12
        assert last_run["duration_ms"] == 1000

    def test_category_filter(self, client):
        response = client.get("/v1/data-sources?category=grid", headers=_auth())

        ids = {d["id"] for d in response.json()["data"]}
        assert ids == {"ds-aemo-nem", "ds-aemo-wem"}

    def test_enabled_filter(self, client):
        response = client.get("/v1/data-sources?enabled=false", headers=_auth())

        body = response.json()
        assert [d["id"] for d in body["data"]] == ["ds-holidays"]
        assert body["meta"]["total"] == 1

    def test_health_filter(self, client):
        response = client.get("/v1/data-sources?health=failing", headers=_auth())

        assert [d["id"] for d in response.json()["data"]] == ["ds-aemo-wem"]

    def test_search_matches_name_or_description(self, client):
        response = client.get("/v1/data-sources?search=bureau", headers=_auth())

        assert [d["id"] for d in response.json()["data"]] == ["ds-bom"]

    def test_sort_desc_by_name(self, client):
        response = client.get("/v1/data-sources?sort=name&order=desc", headers=_auth())

        names = [d["name"] for d in response.json()["data"]]
        assert names == sorted(names, reverse=True)

    def test_pagination_limit_and_cursor(self, client):
        first = client.get("/v1/data-sources?limit=2", headers=_auth())
        assert first.status_code == 200
        first_body = first.json()
        assert len(first_body["data"]) == 2
        assert first_body["has_more"] is True
        assert first_body["next_cursor"] is not None

        second = client.get(
            f"/v1/data-sources?limit=2&cursor={first_body['next_cursor']}",
            headers=_auth(),
        )
        second_body = second.json()
        first_ids = {d["id"] for d in first_body["data"]}
        second_ids = {d["id"] for d in second_body["data"]}
        assert first_ids.isdisjoint(second_ids)

    def test_search_over_64_chars_is_422(self, client):
        response = client.get(f"/v1/data-sources?search={'a' * 65}", headers=_auth())

        assert response.status_code == 422

    def test_limit_out_of_range_is_422(self, client):
        response = client.get("/v1/data-sources?limit=0", headers=_auth())

        assert response.status_code == 422

    def test_cache_hit_skips_the_database(self, client, _wire_fakes):
        session, redis = _wire_fakes

        first = client.get("/v1/data-sources", headers=_auth())
        assert first.status_code == 200
        assert redis.set_calls == 1
        queries_after_first_call = len(session.queries)
        assert queries_after_first_call > 0

        second = client.get("/v1/data-sources", headers=_auth())

        assert second.status_code == 200
        assert len(session.queries) == queries_after_first_call
        assert second.json() == first.json()
