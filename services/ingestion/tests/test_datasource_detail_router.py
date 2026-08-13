from __future__ import annotations

from datetime import UTC, datetime

import jwt
import pytest

from app.main import app
from app.api.v1.deps import get_db, get_redis_client
from app.core.config import get_settings
from app.service.datasources import service as datasources_service
from app.service.pipeline.circuit_breaker import CircuitState

NOW = datetime(2026, 1, 1, tzinfo=UTC)

CATALOG_IDS = ["ds-oe", "ds-aemo-nem", "ds-aemo-wem", "ds-bom", "ds-holidays"]


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self, config_rows=None, run_rows=None):
        self.config_rows: dict[str, dict] = {
            r["id"]: dict(r) for r in (config_rows or [])
        }
        self.run_rows = run_rows or []
        self.queries: list[str] = []

    async def execute(self, query, params):
        sql = str(query)
        self.queries.append(sql)

        if sql.strip().startswith("UPDATE meta.data_sources"):
            id_ = params["id"]
            current = dict(
                self.config_rows.get(
                    id_,
                    {"id": id_, "version": 1, "created_at": NOW, "updated_at": NOW},
                )
            )
            current.update(
                {
                    "enabled": params["enabled"],
                    "cron": params["cron"],
                    "timezone": params["timezone"],
                    "description": params["description"],
                    "auth_type": params["auth_type"],
                    "metadata": params["metadata"],
                    "version": int(current.get("version", 1)) + 1,
                    "updated_at": NOW,
                }
            )
            self.config_rows[id_] = current
            return FakeResult([current])

        if "meta.data_sources" in sql:
            ids = set(params["ids"])
            return FakeResult(
                [row for rid, row in self.config_rows.items() if rid in ids]
            )

        if "meta._ingest_log" in sql:
            sources = set(params["sources"])
            return FakeResult([r for r in self.run_rows if r["source"] in sources])

        raise AssertionError(f"unexpected query: {sql}")


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

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


def _fake_get_breaker(name: str) -> FakeBreaker:
    return FakeBreaker()


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
        for id_ in CATALOG_IDS
    ]


def _token(role: str, sub: str = "diptu") -> str:
    settings = get_settings()
    return jwt.encode(
        {"sub": sub, "role": role},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _auth(role: str = "analyst", sub: str = "diptu") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(role, sub)}"}


@pytest.fixture
def wired(monkeypatch):
    session = FakeSession(config_rows=_seeded_config_rows())
    redis = FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis
    monkeypatch.setattr(datasources_service, "get_breaker", _fake_get_breaker)
    yield session, redis
    app.dependency_overrides.clear()


class TestGetOne:
    def test_no_token_succeeds(self, client, wired):
        """No auth required for now."""
        response = client.get("/v1/data-sources/ds-aemo-nem")

        assert response.status_code == 200

    def test_unknown_id_is_404(self, client, wired):
        response = client.get("/v1/data-sources/ds-nonexistent", headers=_auth())

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_analyst_can_read(self, client, wired):
        response = client.get("/v1/data-sources/ds-aemo-nem", headers=_auth("analyst"))

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == "ds-aemo-nem"
        assert body["schedule"]["cron"] == "*/15 * * * *"
        assert body["version"] == 1

    def test_cache_hit_skips_the_database(self, client, wired):
        session, redis = wired

        first = client.get("/v1/data-sources/ds-bom", headers=_auth())
        assert first.status_code == 200
        queries_after_first = len(session.queries)
        assert queries_after_first > 0

        second = client.get("/v1/data-sources/ds-bom", headers=_auth())

        assert second.status_code == 200
        assert len(session.queries) == queries_after_first
        assert second.json() == first.json()
        assert "datasources:one:v1:ds-bom" in redis.store


class TestPatchOne:
    def test_no_token_succeeds(self, client, wired):
        """No auth required for now."""
        response = client.patch(
            "/v1/data-sources/ds-aemo-nem", json={"description": "no auth needed"}
        )

        assert response.status_code == 200
        assert response.json()["metadata"]["last_edited_by"] == "public"

    def test_unknown_id_is_404(self, client, wired):
        response = client.patch(
            "/v1/data-sources/ds-nonexistent",
            json={"description": "x"},
            headers=_auth("admin"),
        )

        assert response.status_code == 404

    def test_updates_cron_timezone_and_description(self, client, wired):
        response = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={
                "schedule": {"cron": "*/10 * * * *", "timezone": "Australia/Sydney"},
                "description": "Updated to clarify regional coverage",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["schedule"]["cron"] == "*/10 * * * *"
        assert body["schedule"]["cadence"] == "Every 10 minutes"
        assert body["schedule"]["timezone"] == "Australia/Sydney"
        assert body["description"] == "Updated to clarify regional coverage"
        assert body["version"] == 2
        assert body["metadata"]["last_edited_by"] == "public"

    def test_metadata_merges_instead_of_replacing(self, client, wired):
        session, _ = wired
        session.config_rows["ds-bom"]["metadata"] = {"owner_team": "data-eng"}

        response = client.patch(
            "/v1/data-sources/ds-bom",
            json={"metadata": {"data_card_id": "card-123"}},
            headers=_auth("admin"),
        )

        assert response.status_code == 200
        metadata = response.json()["metadata"]
        assert metadata["owner_team"] == "data-eng"
        assert metadata["data_card_id"] == "card-123"

    def test_auth_type_update(self, client, wired):
        response = client.patch(
            "/v1/data-sources/ds-bom",
            json={"auth": {"type": "oauth2"}},
            headers=_auth("admin"),
        )

        assert response.status_code == 200
        assert response.json()["auth"]["type"] == "oauth2"

    def test_enabled_toggle_flips_health_to_paused(self, client, wired):
        response = client.patch(
            "/v1/data-sources/ds-holidays",
            json={"schedule": {"enabled": False}},
            headers=_auth("admin"),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["schedule"]["enabled"] is False
        assert body["health"]["status"] == "paused"

    def test_invalid_cron_is_400(self, client, wired):
        response = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"schedule": {"cron": "not a cron"}},
            headers=_auth("admin"),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_cron"

    def test_invalid_timezone_is_400(self, client, wired):
        response = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"schedule": {"timezone": "Mars/Olympus_Mons"}},
            headers=_auth("admin"),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_timezone"

    def test_description_over_500_chars_is_422(self, client, wired):
        response = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"description": "a" * 501},
            headers=_auth("admin"),
        )

        assert response.status_code == 422

    def test_if_match_mismatch_is_409(self, client, wired):
        response = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"description": "x"},
            headers={**_auth("admin"), "If-Match": "99"},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "version_mismatch"

    def test_if_match_matching_version_succeeds(self, client, wired):
        response = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"description": "x"},
            headers={**_auth("admin"), "If-Match": "1"},
        )

        assert response.status_code == 200
        assert response.json()["version"] == 2

    def test_patch_invalidates_list_and_single_caches(self, client, wired):
        session, redis = wired

        # Warm both caches.
        client.get("/v1/data-sources", headers=_auth())
        client.get("/v1/data-sources/ds-aemo-nem", headers=_auth())
        assert any(k.startswith("datasources:list:v1:") for k in redis.store)
        assert "datasources:one:v1:ds-aemo-nem" in redis.store

        response = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"description": "invalidate me"},
            headers=_auth("admin"),
        )
        assert response.status_code == 200

        assert not any(k.startswith("datasources:list:v1:") for k in redis.store)
        assert "datasources:one:v1:ds-aemo-nem" not in redis.store
