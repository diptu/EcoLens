from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.api.v1.deps import get_db
from app.main import app

NOW = datetime(2026, 1, 1, tzinfo=UTC)
RUN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0][0] if self._rows else 0


class FakeSession:
    def __init__(self, run_row=None, anomaly_count=0):
        self.run_row = run_row
        self.anomaly_count = anomaly_count
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.queries.append((sql, params))

        if "FROM meta._ingest_log" in sql:
            if self.run_row is None or self.run_row["id"] != uuid.UUID(params["id"]):
                return FakeResult([])
            return FakeResult([self.run_row])
        if "FROM meta.anomalies" in sql:
            return FakeResult([[self.anomaly_count]])
        raise AssertionError(f"unexpected query: {sql}")


def _wire(session):
    app.dependency_overrides[get_db] = lambda: session


def _unwire():
    app.dependency_overrides.clear()


class TestGetIngestionRun:
    def test_no_auth_required(self, client):
        _wire(FakeSession(run_row=None))
        try:
            response = client.get(f"/v1/ingestion/runs/{RUN_ID}")
        finally:
            _unwire()

        assert response.status_code == 404  # open, but this run doesn't exist

    def test_unknown_id_is_404(self, client):
        _wire(FakeSession(run_row=None))
        try:
            response = client.get(f"/v1/ingestion/runs/{RUN_ID}")
        finally:
            _unwire()

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_malformed_id_is_422(self, client):
        response = client.get("/v1/ingestion/runs/not-a-uuid")

        assert response.status_code == 422

    def test_returns_a_staged_run_with_derived_fields(self, client):
        row = {
            "id": RUN_ID,
            "source": "bom",
            "status": "staged",
            "triggered_by": "manual",
            "window_start": None,
            "window_end": None,
            "hostname": "worker-1",
            "started_at": NOW,
            "finished_at": NOW + timedelta(seconds=2),
            "rows_landed": 288,
            "rows_loaded": None,
            "error_message": None,
            "circuit_breaker_state": "closed",
        }
        _wire(FakeSession(run_row=row, anomaly_count=3))
        try:
            response = client.get(f"/v1/ingestion/runs/{RUN_ID}")
        finally:
            _unwire()

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(RUN_ID)
        assert body["source"] == "bom"
        assert body["status"] == "staged"
        assert body["duration_ms"] == 2000
        assert body["rows_landed"] == 288
        assert body["anomalies_flagged"] == 3
        assert body["circuit_breaker_state"] == "closed"

    def test_running_run_has_no_duration(self, client):
        row = {
            "id": RUN_ID,
            "source": "oe",
            "status": "running",
            "triggered_by": "schedule",
            "window_start": None,
            "window_end": None,
            "hostname": "worker-1",
            "started_at": NOW,
            "finished_at": None,
            "rows_landed": None,
            "rows_loaded": None,
            "error_message": None,
            "circuit_breaker_state": None,
        }
        _wire(FakeSession(run_row=row, anomaly_count=0))
        try:
            response = client.get(f"/v1/ingestion/runs/{RUN_ID}")
        finally:
            _unwire()

        assert response.status_code == 200
        body = response.json()
        assert body["duration_ms"] is None
        assert body["finished_at"] is None
        assert body["anomalies_flagged"] == 0

    def test_failed_run_surfaces_the_error_message(self, client):
        row = {
            "id": RUN_ID,
            "source": "aemo-nem",
            "status": "failed",
            "triggered_by": "manual",
            "window_start": None,
            "window_end": None,
            "hostname": "worker-1",
            "started_at": NOW,
            "finished_at": NOW + timedelta(seconds=1),
            "rows_landed": None,
            "rows_loaded": None,
            "error_message": "upstream timeout",
            "circuit_breaker_state": "open",
        }
        _wire(FakeSession(run_row=row, anomaly_count=0))
        try:
            response = client.get(f"/v1/ingestion/runs/{RUN_ID}")
        finally:
            _unwire()

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["error_message"] == "upstream timeout"
        assert body["circuit_breaker_state"] == "open"
