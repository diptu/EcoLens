from datetime import UTC, datetime

import jwt
import pytest

from app.api.v1.ingest import routes as ingest_routes
from app.main import app
from app.api.v1.deps import get_db
from app.core.config import get_settings
from app.service.pipeline.tasks import registry


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _token(role: str, sub: str = "diptu") -> str:
    settings = get_settings()
    return jwt.encode(
        {"sub": sub, "role": role},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _auth(role: str = "admin", sub: str = "diptu") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(role, sub)}"}


def test_router_sources_match_the_registry():
    # Regression guard: SourceKey is a hardcoded Literal (needed for
    # FastAPI's OpenAPI schema / 422 validation) that has to be kept in
    # sync with registry.SOURCES by hand. Catch drift here instead of at
    # request time.
    from app.api.v1.ingest.routes import SourceKey

    assert set(SourceKey.__args__) == set(registry.SOURCES)


class TestTriggerIngest:
    def test_requires_auth(self, client):
        response = client.post("/v1/ingest/bom")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"

    def test_analyst_role_is_forbidden(self, client):
        response = client.post("/v1/ingest/bom", headers=_auth("analyst"))

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"

    def test_successful_trigger_returns_rows_staged(self, client, monkeypatch):
        async def fake_run_source(key, **kwargs):
            assert key == "bom"
            assert kwargs == {"lookback_minutes": 45}
            return 288

        monkeypatch.setattr(ingest_routes, "run_source", fake_run_source)

        response = client.post(
            "/v1/ingest/bom", json={"lookback_minutes": 45}, headers=_auth()
        )

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "run_id": None,
            "source": "bom",
            "status": "staged",
            "rows_staged": 288,
        }

    def test_zero_rows_reports_success_not_staged(self, client, monkeypatch):
        # _common.standard_run only takes the immediately-terminal
        # "success" path for an empty fetch (nothing to stage or sync) —
        # the router mirrors that same rows==0 heuristic.
        async def fake_run_source(key, **kwargs):
            return 0

        monkeypatch.setattr(ingest_routes, "run_source", fake_run_source)

        response = client.post("/v1/ingest/bom", headers=_auth())

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["rows_staged"] == 0

    def test_holidays_uses_year_not_lookback_minutes(self, client, monkeypatch):
        captured = {}

        async def fake_run_source(key, **kwargs):
            captured["key"] = key
            captured["kwargs"] = kwargs
            return 42

        monkeypatch.setattr(ingest_routes, "run_source", fake_run_source)

        response = client.post(
            "/v1/ingest/holidays", json={"year": 2030}, headers=_auth()
        )

        assert response.status_code == 200
        assert captured == {"key": "holidays", "kwargs": {"year": 2030}}

    def test_no_body_omits_all_kwargs(self, client, monkeypatch):
        captured = {}

        async def fake_run_source(key, **kwargs):
            captured["kwargs"] = kwargs
            return 0

        monkeypatch.setattr(ingest_routes, "run_source", fake_run_source)

        response = client.post("/v1/ingest/oe", headers=_auth())

        assert response.status_code == 200
        assert captured["kwargs"] == {}

    def test_invalid_source_returns_422(self, client):
        response = client.post("/v1/ingest/nonexistent", headers=_auth())

        assert response.status_code == 422

    def test_failure_returns_500_with_error_envelope(self, client, monkeypatch):
        async def fake_run_source(key, **kwargs):
            raise RuntimeError("upstream is down")

        monkeypatch.setattr(ingest_routes, "run_source", fake_run_source)

        response = client.post("/v1/ingest/aemo-nem", headers=_auth())

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "internal"
        assert "upstream is down" in body["error"]["message"]


class TestListIngestRuns:
    def test_requires_auth(self, client):
        response = client.get("/v1/ingest/runs")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"

    def test_analyst_role_is_allowed(self, client):
        class FakeResult:
            def mappings(self):
                return self

            def all(self):
                return []

        class FakeSession:
            async def execute(self, query, params):
                return FakeResult()

        app.dependency_overrides[get_db] = lambda: FakeSession()

        response = client.get("/v1/ingest/runs", headers=_auth("analyst"))

        assert response.status_code == 200

    def test_returns_rows_from_meta_ingest_log(self, client):
        rows = [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "source": "bom",
                "status": "success",
                "started_at": datetime(2026, 1, 1, tzinfo=UTC),
                "finished_at": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
                "rows_loaded": 288,
                "error_message": None,
            }
        ]

        class FakeResult:
            def mappings(self):
                return self

            def all(self):
                return rows

        class FakeSession:
            async def execute(self, query, params):
                return FakeResult()

        app.dependency_overrides[get_db] = lambda: FakeSession()

        response = client.get("/v1/ingest/runs", headers=_auth())

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["run_id"] == "11111111-1111-1111-1111-111111111111"
        assert body[0]["rows_loaded"] == 288
        assert body[0]["error"] is None

    def test_source_filter_is_forwarded_to_the_query(self, client):
        captured = {}

        class FakeResult:
            def mappings(self):
                return self

            def all(self):
                return []

        class FakeSession:
            async def execute(self, query, params):
                captured["query"] = str(query)
                captured["params"] = params
                return FakeResult()

        app.dependency_overrides[get_db] = lambda: FakeSession()

        response = client.get("/v1/ingest/runs?source=bom&limit=5", headers=_auth())

        assert response.status_code == 200
        assert captured["params"]["source"] == "bom"
        assert captured["params"]["limit"] == 5
        assert "WHERE source = :source" in captured["query"]

    def test_limit_out_of_range_returns_422(self, client):
        response = client.get("/v1/ingest/runs?limit=0", headers=_auth())

        assert response.status_code == 422
