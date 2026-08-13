"""Router-level smoke tests for `GET /v1/ingestion/public/{pipelines,
runs}` — the service-layer logic itself is covered in
`test_public_pipelines_service.py`; this just confirms the routes are
wired up, open (no auth), and return the expected shape end to end."""

from __future__ import annotations

from app.api.v1.deps import get_db
from app.main import app


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar(self):
        return self._rows[0][0] if self._rows else 0


class FakeSession:
    async def execute(self, query, params=None):
        sql = str(query)
        if "FROM meta._ingest_log l" in sql and "ORDER BY" in sql:
            return FakeResult([])
        if "count(*)" in sql:
            return FakeResult([(0,)])
        return FakeResult([])


def _wire():
    app.dependency_overrides[get_db] = lambda: FakeSession()


def _unwire():
    app.dependency_overrides.clear()


class TestPublicPipelinesEndpoint:
    def test_no_auth_required_and_returns_all_five_sources(self, client):
        _wire()
        try:
            response = client.get("/v1/ingestion/public/pipelines")
        finally:
            _unwire()

        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total"] == 5
        assert len(body["data"]) == 5

    def test_pipeline_entries_report_the_real_beat_cadence(self, client):
        _wire()
        try:
            response = client.get("/v1/ingestion/public/pipelines")
        finally:
            _unwire()

        oe = next(p for p in response.json()["data"] if p["id"] == "ds-oe")
        assert oe["schedule"]["cron"] == "*/30 * * * *"
        assert oe["schedule"]["enabled"] is True


class TestPublicRunsEndpoint:
    def test_no_auth_required(self, client):
        _wire()
        try:
            response = client.get("/v1/ingestion/public/runs")
        finally:
            _unwire()

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["has_more"] is False

    def test_accepts_filter_query_params(self, client):
        _wire()
        try:
            response = client.get(
                "/v1/ingestion/public/runs",
                params={"source_id": "ds-oe", "status": "failed", "limit": 10},
            )
        finally:
            _unwire()

        assert response.status_code == 200

    def test_limit_out_of_range_is_422(self, client):
        _wire()
        try:
            response = client.get("/v1/ingestion/public/runs", params={"limit": 10000})
        finally:
            _unwire()

        assert response.status_code == 422
