from __future__ import annotations

import pytest

from app.api.v1.deps import get_redis_client
from app.api.v1.ingest import routes as ingest_routes
from app.main import app
from app.service.pipeline import backfill_jobs

# Captured once, before any test monkeypatches `backfill_jobs.
# run_in_background` -- the real reference tests that want genuine
# background execution restore it to (see `redis_wired`'s own
# docstring for why it's no-op'd by default).
_REAL_RUN_IN_BACKGROUND = backfill_jobs.run_in_background


class TestIngestSourceEndpoint:
    def test_unknown_source_is_422(self, client):
        """`source` is a `Literal` (`IngestSourceKey`), not a bare `str`
        -- FastAPI validates it against the enumerated choices before
        the handler runs, same as this API's other `Literal`-typed
        params (`category`/`sort`/`order` on `GET /v1/data-sources`).
        This is also what makes `/docs` render `source` as a dropdown
        instead of a free-text box."""
        response = client.post("/v1/ingest/nonexistent")

        assert response.status_code == 422

    def test_openapi_schema_exposes_source_as_an_enum(self, client):
        """The actual "is this a dropdown in /docs" check -- FastAPI/
        Pydantic render a `Literal`-typed path param as an `enum` in the
        generated OpenAPI schema, which is what Swagger UI turns into a
        `<select>`."""
        schema = client.get("/openapi.json").json()
        source_param = next(
            p
            for p in schema["paths"]["/v1/ingest/{source}"]["post"]["parameters"]
            if p["name"] == "source"
        )
        assert set(source_param["schema"]["enum"]) == {
            "oe",
            "aemo-nem",
            "aemo-wem",
            "bom",
            "holidays",
        }

    def test_no_auth_required(self, client, monkeypatch):
        async def fake_run_source(key, **kwargs):
            return 288

        monkeypatch.setattr(ingest_routes, "run_source", fake_run_source)

        response = client.post("/v1/ingest/bom")

        assert response.status_code == 200

    def test_successful_ingest_returns_rows_staged(self, client, monkeypatch):
        captured = {}

        async def fake_run_source(key, **kwargs):
            captured["key"] = key
            captured["kwargs"] = kwargs
            return 288

        monkeypatch.setattr(ingest_routes, "run_source", fake_run_source)

        response = client.post("/v1/ingest/bom")

        assert response.status_code == 200
        body = response.json()
        assert body == {"source": "bom", "rows_staged": 288, "triggered_by": "manual"}
        assert captured == {"key": "bom", "kwargs": {"triggered_by": "manual"}}

    def test_lookback_minutes_is_forwarded(self, client, monkeypatch):
        captured = {}

        async def fake_run_source(key, **kwargs):
            captured["kwargs"] = kwargs
            return 12

        monkeypatch.setattr(ingest_routes, "run_source", fake_run_source)

        response = client.post("/v1/ingest/aemo-nem", json={"lookback_minutes": 60})

        assert response.status_code == 200
        assert captured["kwargs"] == {"triggered_by": "manual", "lookback_minutes": 60}

    def test_year_is_forwarded_for_holidays(self, client, monkeypatch):
        captured = {}

        async def fake_run_source(key, **kwargs):
            captured["kwargs"] = kwargs
            return 42

        monkeypatch.setattr(ingest_routes, "run_source", fake_run_source)

        response = client.post("/v1/ingest/holidays", json={"year": 2030})

        assert response.status_code == 200
        assert captured["kwargs"] == {"triggered_by": "manual", "year": 2030}

    def test_triggered_by_is_forwarded(self, client, monkeypatch):
        captured = {}

        async def fake_run_source(key, **kwargs):
            captured["kwargs"] = kwargs
            return 5

        monkeypatch.setattr(ingest_routes, "run_source", fake_run_source)

        response = client.post("/v1/ingest/bom", json={"triggered_by": "backfill"})

        assert response.status_code == 200
        assert captured["kwargs"]["triggered_by"] == "backfill"
        assert response.json()["triggered_by"] == "backfill"

    def test_invalid_triggered_by_is_422(self, client):
        response = client.post("/v1/ingest/bom", json={"triggered_by": "not-a-choice"})

        assert response.status_code == 422

    def test_lookback_minutes_below_1_is_422(self, client):
        response = client.post("/v1/ingest/bom", json={"lookback_minutes": 0})

        assert response.status_code == 422

    def test_upstream_failure_returns_502(self, client, monkeypatch):
        async def fake_run_source(key, **kwargs):
            raise RuntimeError("upstream is down")

        monkeypatch.setattr(ingest_routes, "run_source", fake_run_source)

        response = client.post("/v1/ingest/bom")

        assert response.status_code == 502
        body = response.json()
        assert body["error"]["code"] == "ingest_failed"
        assert "upstream is down" in body["error"]["message"]


@pytest.mark.anyio
class TestIngestSourceEndpointLive:
    """Exercises the real `registry.run_source` (not monkeypatched) for
    one fast, no-network source -- `holidays` builds its table in
    memory, no HTTP call, no real DB/Redis/RabbitMQ needed to fail
    gracefully-ish. Confirms the route's kwarg-forwarding wiring against
    the real function signature, not just a fake matching whatever
    shape this test file assumes it has."""

    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    def test_holidays_reaches_real_run_source(self, client):
        # No mocks: a real call all the way to `_common.standard_run`,
        # which will fail at the DB-write step (no real Postgres/Redis
        # in this test env) -- confirmed as a 502 wrapping that error,
        # not a 404/422 from this router's own validation.
        response = client.post("/v1/ingest/holidays", json={"year": 2030})

        assert response.status_code in (200, 502)
        if response.status_code == 502:
            assert response.json()["error"]["code"] == "ingest_failed"


class FakeRedis:
    """Same minimal in-memory stand-in `test_datasource_actions_router.
    py`'s own `FakeRedis` is -- just enough `get`/`set`/`delete` for
    `backfill_jobs`' lock/result keys, no real Redis needed."""

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


@pytest.fixture
def redis_wired(monkeypatch):
    """Overrides `get_redis_client` with a `FakeRedis` for the duration
    of one test, and by default no-ops `backfill_jobs.run_in_background`
    so triggering a backfill doesn't also run the real `pipeline.
    backfill.backfill` synchronously (TestClient runs `BackgroundTasks`
    to completion before `client.post(...)` returns) -- tests that want
    the real background execution call `monkeypatch.setattr(backfill_
    jobs, "run_in_background", _REAL_RUN_IN_BACKGROUND)` themselves to
    undo this."""
    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = lambda: redis

    async def noop_run_in_background(*args, **kwargs):
        pass

    # `ingest_routes.backfill_jobs` is the same module object as
    # `backfill_jobs` here -- one patch covers both access paths.
    monkeypatch.setattr(backfill_jobs, "run_in_background", noop_run_in_background)
    try:
        yield redis
    finally:
        app.dependency_overrides.clear()


class TestIngestBackfillEndpoint:
    def test_holidays_is_not_a_valid_backfill_source(self, client):
        """`holidays` is excluded from `BackfillableSourceKey` -- an
        annual snapshot, not a per-day time series (same reasoning as
        `pipeline.backfill.BACKFILLABLE_SOURCES`)."""
        response = client.post(
            "/v1/ingest/holidays/backfill",
            json={"start": "2026-01-01", "end": "2026-01-02"},
        )

        assert response.status_code == 422

    def test_openapi_schema_excludes_holidays_from_backfill_dropdown(self, client):
        schema = client.get("/openapi.json").json()
        source_param = next(
            p
            for p in schema["paths"]["/v1/ingest/{source}/backfill"]["post"][
                "parameters"
            ]
            if p["name"] == "source"
        )
        assert set(source_param["schema"]["enum"]) == {
            "oe",
            "aemo-nem",
            "aemo-wem",
            "bom",
        }

    def test_no_auth_required(self, client, redis_wired):
        """Trigger is deliberately open — no bearer token needed at all."""
        response = client.post(
            "/v1/ingest/bom/backfill",
            json={"start": "2026-01-01", "end": "2026-01-01"},
        )

        assert response.status_code == 202

    def test_start_after_end_is_400(self, client, redis_wired):
        response = client.post(
            "/v1/ingest/bom/backfill",
            json={"start": "2026-01-08", "end": "2026-01-01"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_range"

    def test_range_over_90_days_is_400(self, client, redis_wired):
        response = client.post(
            "/v1/ingest/bom/backfill",
            json={"start": "2025-01-01", "end": "2026-01-01"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "range_too_large"

    def test_returns_202_with_a_backfill_id_and_totals(self, client, redis_wired):
        response = client.post(
            "/v1/ingest/aemo-nem/backfill",
            json={
                "start": "2026-07-01",
                "end": "2026-07-03",
                "lookback_minutes": 60,
            },
        )

        assert response.status_code == 202
        body = response.json()
        assert body["backfill_id"].startswith("ibf-")
        assert body["source"] == "aemo-nem"
        assert body["start"] == "2026-07-01"
        assert body["end"] == "2026-07-03"
        assert body["total_days"] == 3
        assert body["lookback_minutes"] == 60
        assert "queued_at" in body

    def test_default_lookback_minutes_is_1440(self, client, redis_wired):
        response = client.post(
            "/v1/ingest/bom/backfill",
            json={"start": "2026-01-01", "end": "2026-01-01"},
        )

        assert response.json()["lookback_minutes"] == 1440

    def test_backfill_in_progress_is_409(self, client, redis_wired):
        redis_wired.store["ingest_backfill:lock:bom"] = "already-running"

        response = client.post(
            "/v1/ingest/bom/backfill",
            json={"start": "2026-01-01", "end": "2026-01-01"},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "backfill_in_progress"

    def test_dispatches_the_real_backfill_run_in_the_background(
        self, client, redis_wired, monkeypatch
    ):
        """Undoes `redis_wired`'s no-op so the real `backfill_jobs.
        run_in_background` runs (synchronously, within `client.post`,
        same as `test_datasource_actions_router.py`'s equivalent) against
        a faked `pipeline.backfill.backfill` -- confirms the trigger
        endpoint's background task is wired to the real function with
        the right args, and that the lock is cleared and a result cached
        afterward."""
        from datetime import date

        captured = {}

        async def fake_backfill(sources, start, end, lookback_minutes):
            captured["sources"] = sources
            captured["start"] = start
            captured["end"] = end
            captured["lookback_minutes"] = lookback_minutes
            return {("bom", date(2026, 7, 1)): "success"}

        monkeypatch.setattr(backfill_jobs, "run_backfill", fake_backfill)
        monkeypatch.setattr(backfill_jobs, "run_in_background", _REAL_RUN_IN_BACKGROUND)

        response = client.post(
            "/v1/ingest/bom/backfill",
            json={"start": "2026-07-01", "end": "2026-07-01"},
        )

        assert response.status_code == 202
        assert captured["sources"] == ("bom",)
        assert captured["start"].isoformat() == "2026-07-01"
        assert captured["end"].isoformat() == "2026-07-01"
        assert captured["lookback_minutes"] == 1440
        assert "ingest_backfill:lock:bom" not in redis_wired.store
        assert "ingest_backfill:result:bom" in redis_wired.store


class TestIngestBackfillStatusEndpoint:
    def test_unknown_source_is_422(self, client, redis_wired):
        response = client.get("/v1/ingest/nonexistent/backfill/status")

        assert response.status_code == 422

    def test_not_running_and_never_triggered(self, client, redis_wired):
        response = client.get("/v1/ingest/bom/backfill/status")

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "source": "bom",
            "running": False,
            "trigger": None,
            "result": None,
        }

    def test_running_reflects_the_lock_contents(self, client, redis_wired):
        # `redis_wired`'s no-op `run_in_background` never clears the
        # lock `trigger()` sets, so it's still "running" from the status
        # endpoint's POV once the POST returns.
        trigger_response = client.post(
            "/v1/ingest/bom/backfill",
            json={"start": "2026-01-01", "end": "2026-01-01"},
        )
        backfill_id = trigger_response.json()["backfill_id"]

        response = client.get("/v1/ingest/bom/backfill/status")

        assert response.status_code == 200
        body = response.json()
        assert body["running"] is True
        assert body["trigger"]["backfill_id"] == backfill_id
        assert body["result"] is None

    def test_result_available_after_a_completed_background_run(
        self, client, redis_wired, monkeypatch
    ):
        from datetime import date

        async def fake_backfill(sources, start, end, lookback_minutes):
            return {
                ("bom", date(2026, 7, 1)): "success",
                ("bom", date(2026, 7, 2)): "skipped",
            }

        monkeypatch.setattr(backfill_jobs, "run_backfill", fake_backfill)
        monkeypatch.setattr(backfill_jobs, "run_in_background", _REAL_RUN_IN_BACKGROUND)

        client.post(
            "/v1/ingest/bom/backfill",
            json={"start": "2026-07-01", "end": "2026-07-02"},
        )

        response = client.get("/v1/ingest/bom/backfill/status")

        assert response.status_code == 200
        body = response.json()
        assert body["running"] is False
        assert body["trigger"] is None
        assert body["result"]["source"] == "bom"
        assert body["result"]["succeeded"] == 1
        assert body["result"]["skipped"] == 1
        assert body["result"]["days"] == [
            {"day": "2026-07-01", "outcome": "success"},
            {"day": "2026-07-02", "outcome": "skipped"},
        ]
