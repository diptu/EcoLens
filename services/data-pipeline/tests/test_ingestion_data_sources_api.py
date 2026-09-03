"""Tests for ecolens.ingestion.api.data_sources_routes (`GET`/`PATCH
/v1/data-sources[/{id}]`).

`duckdb_store.latest_fetched_at` and both Redis touchpoints
(`data_sources_routes.get_redis_client` for the circuit breaker,
`data_sources_cache.get_redis_client` for the 30s response cache) are
monkeypatched -- no real DuckDB file or Redis server touched. `PATCH`
genuinely writes an overrides file and appends run history, so the
`client` fixture chdirs to `tmp_path` first -- same real-repo-leak
guard `test_ingestion_api.py`'s own fixture uses.
"""

from __future__ import annotations

import fnmatch
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ecolens.ingestion.api.data_sources_routes as api_module
import ecolens.ingestion.core.data_sources_cache as cache_module
import ecolens.ingestion.core.run_locks as locks_module
from ecolens.ingestion.core.run_history import record_run
from ecolens.ingestion.core.settings import get_ingestion_settings

_NOW = datetime.now(timezone.utc)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_ingestion_settings.cache_clear()

    app = FastAPI()
    app.include_router(api_module.router)
    with TestClient(app) as c:
        yield c
    get_ingestion_settings.cache_clear()


def _patch_latest_fetched_at(
    monkeypatch, values: dict[str, datetime | None] | None = None
):
    values = values or {}

    def fake(source: str, *, db_path=None):
        return values.get(source)

    monkeypatch.setattr(api_module.duckdb_store, "latest_fetched_at", fake)


def _patch_redis_unavailable(monkeypatch):
    """Disables both the circuit-breaker Redis lookup and the response
    cache -- most tests want deterministic, uncached behavior.
    """

    def raise_connect_error():
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(api_module, "get_redis_client", raise_connect_error)
    monkeypatch.setattr(cache_module, "get_redis_client", raise_connect_error)


def _patch_circuit_breaker_state(monkeypatch, state: dict):
    fake_breaker = MagicMock()
    fake_breaker.get_state = AsyncMock(return_value=state)
    monkeypatch.setattr(
        api_module, "CircuitBreaker", lambda source, redis: fake_breaker
    )
    monkeypatch.setattr(api_module, "get_redis_client", lambda: object())
    monkeypatch.setattr(
        cache_module,
        "get_redis_client",
        lambda: (_ for _ in ()).throw(ConnectionError()),
    )


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def delete(self, *keys: str) -> int:
        n = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                n += 1
        return n

    async def scan(self, cursor: int, match: str, count: int) -> tuple[int, list[str]]:
        return 0, [k for k in self._store if fnmatch.fnmatch(k, match)]


def _patch_working_cache(monkeypatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(cache_module, "get_redis_client", lambda: fake)
    return fake


class TestListDataSources:
    def test_returns_all_five_real_sources(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources")
        assert r.status_code == 200
        body = r.json()
        ids = {s["id"] for s in body["data"]}
        assert ids == {
            "ds-aemo-nem",
            "ds-aemo-wem",
            "ds-openelectricity",
            "ds-bom",
            "ds-aemo-holidays",
        }
        assert body["meta"]["total"] == 5

    def test_default_sort_is_alphabetical_by_name(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources")
        names = [s["name"] for s in r.json()["data"]]
        assert names == sorted(names)

    def test_response_envelope_shape(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources")
        body = r.json()
        assert set(body) == {"meta", "data", "next_cursor", "has_more"}
        assert set(body["meta"]) == {
            "total",
            "enabled_count",
            "disabled_count",
            "healthy_count",
            "degraded_count",
            "failing_count",
            "paused_count",
            "as_of",
            "next_refresh_at",
        }

    def test_source_item_shape(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources")
        item = r.json()["data"][0]
        assert set(item) == {
            "id",
            "name",
            "category",
            "description",
            "url",
            "license",
            "auth",
            "schedule",
            "health",
            "last_run",
            "regions",
            "metadata",
            "version",
            "created_at",
            "updated_at",
        }
        assert set(item["schedule"]) == {
            "cron",
            "cadence",
            "timezone",
            "enabled",
            "next_run_at",
            "last_run_at",
        }
        assert set(item["health"]) == {
            "status",
            "success_rate_pct_24h",
            "success_rate_pct_7d",
            "p50_duration_ms",
            "p95_duration_ms",
            "p99_duration_ms",
            "consecutive_failures",
            "circuit_breaker",
            "last_check_at",
        }

    def test_default_cron_and_enabled_before_any_patch(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources")
        for source in r.json()["data"]:
            assert source["schedule"]["cron"] == "*/15 * * * *"
            assert source["schedule"]["enabled"] is True
            assert source["version"] == 1

    def test_category_filter(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources", params={"category": "weather"})
        ids = [s["id"] for s in r.json()["data"]]
        assert ids == ["ds-bom"]

    def test_enabled_filter(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        client.patch("/v1/data-sources/ds-bom", json={"schedule": {"enabled": False}})
        r = client.get("/v1/data-sources", params={"enabled": "false"})
        ids = [s["id"] for s in r.json()["data"]]
        assert ids == ["ds-bom"]

    def test_search_filter_matches_name(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources", params={"search": "bureau"})
        ids = [s["id"] for s in r.json()["data"]]
        assert ids == ["ds-bom"]

    def test_sort_by_name_desc(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources", params={"sort": "name", "order": "desc"})
        names = [s["name"] for s in r.json()["data"]]
        assert names == sorted(names, reverse=True)

    def test_pagination_limit_and_has_more(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources", params={"limit": 2})
        body = r.json()
        assert len(body["data"]) == 2
        assert body["has_more"] is True
        assert body["next_cursor"] is not None

    def test_cursor_continues_where_the_previous_page_left_off(
        self, client, monkeypatch
    ):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        first = client.get("/v1/data-sources", params={"limit": 2}).json()
        second = client.get(
            "/v1/data-sources", params={"limit": 2, "cursor": first["next_cursor"]}
        ).json()
        first_ids = {s["id"] for s in first["data"]}
        second_ids = {s["id"] for s in second["data"]}
        assert first_ids.isdisjoint(second_ids)

    def test_last_page_has_more_false_and_no_cursor(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources", params={"limit": 200})
        body = r.json()
        assert body["has_more"] is False
        assert body["next_cursor"] is None

    def test_invalid_cursor_400s(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources", params={"cursor": "not-valid-base64!!"})
        assert r.status_code == 400

    def test_meta_counts_reflect_whole_catalog_not_the_filter(
        self, client, monkeypatch
    ):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        client.patch("/v1/data-sources/ds-bom", json={"schedule": {"enabled": False}})
        r = client.get("/v1/data-sources", params={"category": "grid"})
        body = r.json()
        assert body["meta"]["total"] == 3  # 3 "grid" sources match the filter
        assert body["meta"]["enabled_count"] == 4  # whole catalog, not filtered
        assert body["meta"]["disabled_count"] == 1

    def test_second_call_returns_the_cached_response_unchanged(
        self, client, monkeypatch
    ):
        fetched = {"aemo_nem": _NOW}
        _patch_latest_fetched_at(monkeypatch, fetched)
        _patch_working_cache(monkeypatch)
        monkeypatch.setattr(
            api_module,
            "get_redis_client",
            lambda: (_ for _ in ()).throw(ConnectionError()),
        )

        first = client.get("/v1/data-sources").json()
        # Mutate underlying state directly (bypassing the API, so no
        # cache invalidation happens) -- a genuinely cached second call
        # must still return the *first* response's `as_of`, not a freshly
        # recomputed one.
        fetched["aemo_nem"] = _NOW - timedelta(hours=5)
        second = client.get("/v1/data-sources").json()
        assert second["meta"]["as_of"] == first["meta"]["as_of"]


class TestGetOneDataSource:
    def test_happy_path(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources/ds-aemo-nem")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == "ds-aemo-nem"
        assert body["name"] == "AEMO NEM"
        assert body["regions"] == ["NSW1", "QLD1", "VIC1", "SA1", "TAS1"]

    def test_unknown_id_404s_with_not_found_code(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources/ds-bogus")
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "not_found"

    def test_id_without_ds_prefix_404s(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources/aemo_nem")
        assert r.status_code == 404

    def test_last_run_reflects_recorded_history(self, client, monkeypatch, tmp_path):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        record_run(
            "aemo_nem",
            status="success",
            started_at=_NOW - timedelta(seconds=1),
            finished_at=_NOW,
            records_fetched=12,
            records_inserted=12,
            anomalies_flagged=0,
        )
        r = client.get("/v1/data-sources/ds-aemo-nem")
        last_run_body = r.json()["last_run"]
        assert last_run_body is not None
        assert last_run_body["status"] == "success"
        assert last_run_body["records_fetched"] == 12
        assert last_run_body["duplicates_skipped"] is None  # honestly unavailable

    def test_no_run_history_gives_null_last_run(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources/ds-aemo-nem")
        assert r.json()["last_run"] is None


class TestPatchDataSource:
    def test_unknown_id_404s(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.patch("/v1/data-sources/ds-bogus", json={"description": "x"})
        assert r.status_code == 404

    def test_empty_body_400s(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.patch("/v1/data-sources/ds-aemo-nem", json={})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "empty_patch"

    def test_invalid_cron_400s_with_code(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.patch(
            "/v1/data-sources/ds-aemo-nem", json={"schedule": {"cron": "garbage"}}
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "invalid_cron"

    def test_invalid_timezone_400s_with_code(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.patch(
            "/v1/data-sources/ds-aemo-nem", json={"schedule": {"timezone": "Not/AZone"}}
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "invalid_timezone"

    def test_description_too_long_400s(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.patch(
            "/v1/data-sources/ds-aemo-nem", json={"description": "x" * 501}
        )
        assert r.status_code == 400

    def test_schedule_update_persists_and_is_returned(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"schedule": {"cron": "*/10 * * * *", "enabled": False}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["schedule"]["cron"] == "*/10 * * * *"
        assert body["schedule"]["cadence"] == "Every 10 minutes"
        assert body["schedule"]["enabled"] is False
        assert body["version"] == 2

    def test_description_override_takes_precedence_over_catalog(
        self, client, monkeypatch
    ):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"description": "Updated to clarify regional coverage"},
        )
        assert r.json()["description"] == "Updated to clarify regional coverage"

    def test_auth_type_override(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.patch(
            "/v1/data-sources/ds-openelectricity", json={"auth": {"type": "none"}}
        )
        assert r.json()["auth"]["type"] == "none"

    def test_metadata_merges_across_patches(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"metadata": {"owner_team": "data-eng"}},
        )
        r = client.patch(
            "/v1/data-sources/ds-aemo-nem", json={"metadata": {"schema_version": 3}}
        )
        assert r.json()["metadata"] == {"owner_team": "data-eng", "schema_version": 3}

    def test_if_match_wrong_version_409s(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"description": "x"},
            headers={"If-Match": "99"},
        )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "version_mismatch"

    def test_if_match_correct_version_succeeds(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"description": "x"},
            headers={"If-Match": "1"},
        )
        assert r.status_code == 200

    def test_if_match_non_numeric_409s(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.patch(
            "/v1/data-sources/ds-aemo-nem",
            json={"description": "x"},
            headers={"If-Match": "not-a-number"},
        )
        assert r.status_code == 409

    def test_patch_invalidates_the_list_cache(self, client, monkeypatch):
        fake = _patch_working_cache(monkeypatch)
        _patch_latest_fetched_at(monkeypatch)
        monkeypatch.setattr(
            api_module,
            "get_redis_client",
            lambda: (_ for _ in ()).throw(ConnectionError()),
        )

        client.get("/v1/data-sources")  # populate the list cache
        assert any(k.startswith("datasources:list:v1:") for k in fake._store)

        client.patch("/v1/data-sources/ds-aemo-nem", json={"description": "x"})

        assert not any(k.startswith("datasources:list:v1:") for k in fake._store)


def _patch_no_locks(monkeypatch):
    """Locks degrade to "always allow" without a working Redis -- most
    /run and /backfill tests want deterministic behavior, not
    lock-contention noise.
    """

    def raise_connect_error():
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(locks_module, "get_redis_client", raise_connect_error)


def _patch_ingest(monkeypatch, *, written: int = 5, error: Exception | None = None):
    calls: list[tuple] = []

    async def fake(source_id, start, end):
        calls.append((source_id, start, end))
        if error is not None:
            raise error
        return written

    monkeypatch.setattr(api_module, "_run_ingest_for_range", fake)
    return calls


class TestTriggerRun:
    def test_unknown_id_404s(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        r = client.post("/v1/data-sources/ds-bogus/run")
        assert r.status_code == 404

    def test_happy_path_returns_202(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        r = client.post("/v1/data-sources/ds-aemo-nem/run", json={})
        assert r.status_code == 202
        body = r.json()
        assert body["source_id"] == "ds-aemo-nem"
        assert body["status"] == "queued"
        assert body["run_id"].startswith("run-")

    def test_records_history_after_the_background_task_runs(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch, written=7)
        client.post("/v1/data-sources/ds-aemo-nem/run", json={})
        r = client.get("/v1/data-sources/ds-aemo-nem/history")
        body = r.json()
        assert body["total"] == 1
        assert body["data"][0]["status"] == "success"
        assert body["data"][0]["records_inserted"] == 7
        assert body["data"][0]["trigger"] == "manual"

    def test_zero_written_records_as_empty(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch, written=0)
        client.post("/v1/data-sources/ds-aemo-nem/run", json={})
        r = client.get("/v1/data-sources/ds-aemo-nem/history")
        assert r.json()["data"][0]["status"] == "empty"

    def test_ingest_exception_records_failed_with_error(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch, error=RuntimeError("boom"))
        client.post("/v1/data-sources/ds-aemo-nem/run", json={})
        r = client.get("/v1/data-sources/ds-aemo-nem/history")
        item = r.json()["data"][0]
        assert item["status"] == "failed"
        assert item["error"] == "boom"

    def test_open_circuit_without_force_returns_503(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        _patch_circuit_breaker_state(
            monkeypatch, {"state": "open", "failures": 5, "retry_after_seconds": 100.0}
        )
        r = client.post("/v1/data-sources/ds-aemo-nem/run", json={"force": False})
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "circuit_open"

    def test_open_circuit_with_force_bypasses(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        _patch_circuit_breaker_state(
            monkeypatch, {"state": "open", "failures": 5, "retry_after_seconds": 100.0}
        )
        r = client.post("/v1/data-sources/ds-aemo-nem/run", json={"force": True})
        assert r.status_code == 202

    def test_idempotency_key_returns_cached_response_without_a_second_run(
        self, client, monkeypatch
    ):
        fake_redis = _FakeRedis()
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake_redis)
        monkeypatch.setattr(
            api_module,
            "get_redis_client",
            lambda: (_ for _ in ()).throw(ConnectionError()),
        )
        calls = _patch_ingest(monkeypatch)

        first = client.post(
            "/v1/data-sources/ds-aemo-nem/run",
            headers={"Idempotency-Key": "same-key"},
            json={},
        ).json()
        second = client.post(
            "/v1/data-sources/ds-aemo-nem/run",
            headers={"Idempotency-Key": "same-key"},
            json={},
        ).json()

        assert first["run_id"] == second["run_id"]
        assert len(calls) == 1  # the underlying ingest only actually ran once

    def test_x_reason_header_is_echoed(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        r = client.post(
            "/v1/data-sources/ds-aemo-nem/run",
            headers={"X-Reason": "Manual verification after cron change"},
            json={},
        )
        assert r.json()["reason"] == "Manual verification after cron change"


class TestTriggerBackfill:
    def _body(self, **overrides):
        body = {"start": "2024-05-20T00:00:00Z", "end": "2024-05-22T00:00:00Z"}
        body.update(overrides)
        return body

    def test_unknown_id_404s(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        r = client.post("/v1/data-sources/ds-bogus/backfill", json=self._body())
        assert r.status_code == 404

    def test_happy_path_returns_202_with_chunk_count(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        r = client.post("/v1/data-sources/ds-aemo-nem/backfill", json=self._body())
        assert r.status_code == 202
        body = r.json()
        assert body["total_chunks"] == 2  # 2-day range, P1D default chunk
        assert body["backfill_id"].startswith("bf-")

    def test_start_after_end_400s_invalid_range(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        r = client.post(
            "/v1/data-sources/ds-aemo-nem/backfill",
            json=self._body(start="2024-05-22T00:00:00Z", end="2024-05-20T00:00:00Z"),
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "invalid_range"

    def test_end_in_the_future_400s(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        r = client.post(
            "/v1/data-sources/ds-aemo-nem/backfill",
            json=self._body(start="2024-05-20T00:00:00Z", end="2999-01-01T00:00:00Z"),
        )
        assert r.status_code == 400

    def test_range_over_90_days_400s(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        r = client.post(
            "/v1/data-sources/ds-aemo-nem/backfill",
            json=self._body(start="2020-01-01T00:00:00Z", end="2024-01-01T00:00:00Z"),
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "range_too_large"

    def test_invalid_chunk_duration_400s(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        r = client.post(
            "/v1/data-sources/ds-aemo-nem/backfill",
            json=self._body(chunk="not-a-duration"),
        )
        assert r.status_code == 400

    def test_concurrency_out_of_range_400s(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch)
        r = client.post(
            "/v1/data-sources/ds-aemo-nem/backfill", json=self._body(concurrency=10)
        )
        assert r.status_code == 400

    def test_records_one_history_entry_per_chunk(self, client, monkeypatch):
        _patch_no_locks(monkeypatch)
        _patch_ingest(monkeypatch, written=3)
        client.post(
            "/v1/data-sources/ds-aemo-nem/backfill",
            json=self._body(
                start="2024-05-20T00:00:00Z", end="2024-05-23T00:00:00Z", chunk="P1D"
            ),
        )
        r = client.get("/v1/data-sources/ds-aemo-nem/history")
        body = r.json()
        assert body["total"] == 3  # 3 one-day chunks
        assert all(item["trigger"] == "backfill" for item in body["data"])


class TestDataSourceHealth:
    def test_unknown_id_404s(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources/ds-bogus/health")
        assert r.status_code == 404

    def test_shape(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        r = client.get("/v1/data-sources/ds-aemo-nem/health")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {
            "source_id",
            "status",
            "as_of",
            "success_rate_pct_1h",
            "success_rate_pct_24h",
            "success_rate_pct_7d",
            "success_rate_pct_30d",
            "p50_duration_ms",
            "p95_duration_ms",
            "p99_duration_ms",
            "consecutive_failures",
            "circuit_breaker",
            "last_5_runs",
            "errors_by_code_24h",
        }
        assert set(body["circuit_breaker"]) == {
            "state",
            "opened_at",
            "half_open_at",
            "recovery_seconds",
        }
        assert set(body["errors_by_code_24h"]) == {
            "missing_credentials",
            "timeout",
            "rate_limited",
            "schema_mismatch",
        }

    def test_last_5_runs_most_recent_first(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        for i in range(3):
            record_run(
                "aemo_nem",
                status="success",
                started_at=_NOW - timedelta(minutes=10 - i),
                finished_at=_NOW - timedelta(minutes=9 - i),
                run_id=f"run-{i}",
            )
        r = client.get("/v1/data-sources/ds-aemo-nem/health")
        ids = [x["id"] for x in r.json()["last_5_runs"]]
        assert ids == ["run-2", "run-1", "run-0"]

    def test_error_classification(self, client, monkeypatch):
        _patch_latest_fetched_at(monkeypatch)
        _patch_redis_unavailable(monkeypatch)
        record_run(
            "aemo_nem",
            status="failed",
            started_at=_NOW,
            finished_at=_NOW,
            error="Request timeout after 30s",
        )
        record_run(
            "aemo_nem",
            status="failed",
            started_at=_NOW,
            finished_at=_NOW,
            error="OE_API_KEY not configured",
        )
        r = client.get("/v1/data-sources/ds-aemo-nem/health")
        codes = r.json()["errors_by_code_24h"]
        assert codes["timeout"] == 1
        assert codes["missing_credentials"] == 1


class TestDataSourceHistory:
    def test_unknown_id_404s(self, client, monkeypatch):
        r = client.get("/v1/data-sources/ds-bogus/history")
        assert r.status_code == 404

    def test_empty_history(self, client, monkeypatch):
        r = client.get("/v1/data-sources/ds-aemo-nem/history")
        assert r.status_code == 200
        assert r.json() == {
            "source_id": "ds-aemo-nem",
            "total": 0,
            "data": [],
            "next_cursor": None,
            "has_more": False,
        }

    def test_most_recent_first(self, client, monkeypatch):
        record_run(
            "aemo_nem",
            status="success",
            started_at=_NOW,
            finished_at=_NOW,
            run_id="older",
        )
        record_run(
            "aemo_nem",
            status="success",
            started_at=_NOW + timedelta(seconds=1),
            finished_at=_NOW + timedelta(seconds=1),
            run_id="newer",
        )
        r = client.get("/v1/data-sources/ds-aemo-nem/history")
        ids = [item["id"] for item in r.json()["data"]]
        assert ids == ["newer", "older"]

    def test_status_filter(self, client, monkeypatch):
        record_run(
            "aemo_nem", status="success", started_at=_NOW, finished_at=_NOW, run_id="ok"
        )
        record_run(
            "aemo_nem",
            status="failed",
            started_at=_NOW,
            finished_at=_NOW,
            error="x",
            run_id="bad",
        )
        r = client.get(
            "/v1/data-sources/ds-aemo-nem/history", params={"status": "failed"}
        )
        ids = [item["id"] for item in r.json()["data"]]
        assert ids == ["bad"]

    def test_only_scoped_to_the_requested_source(self, client, monkeypatch):
        record_run("aemo_nem", status="success", started_at=_NOW, finished_at=_NOW)
        record_run("bom", status="success", started_at=_NOW, finished_at=_NOW)
        r = client.get("/v1/data-sources/ds-aemo-nem/history")
        assert r.json()["total"] == 1

    def test_pagination(self, client, monkeypatch):
        for i in range(5):
            record_run(
                "aemo_nem",
                status="success",
                started_at=_NOW + timedelta(seconds=i),
                finished_at=_NOW + timedelta(seconds=i),
                run_id=f"run-{i}",
            )
        r = client.get("/v1/data-sources/ds-aemo-nem/history", params={"limit": 2})
        body = r.json()
        assert len(body["data"]) == 2
        assert body["has_more"] is True
        assert body["total"] == 5

    def test_invalid_cursor_400s(self, client, monkeypatch):
        r = client.get(
            "/v1/data-sources/ds-aemo-nem/history", params={"cursor": "!!!not-valid"}
        )
        assert r.status_code == 400

    def test_duplicates_skipped_is_honestly_null(self, client, monkeypatch):
        record_run("aemo_nem", status="success", started_at=_NOW, finished_at=_NOW)
        r = client.get("/v1/data-sources/ds-aemo-nem/history")
        assert r.json()["data"][0]["duplicates_skipped"] is None
