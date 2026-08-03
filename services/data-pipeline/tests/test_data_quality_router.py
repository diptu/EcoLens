from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.api.v1.data_quality import routes as data_quality_routes
from app.main import app
from app.api.v1.deps import get_db, get_redis_client
from app.core.config import get_settings

NOW = datetime.now(UTC)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(
        self,
        *,
        run_rows=(),
        anomaly_cluster_rows=(),
        outlier_rows=(),
        drift_rows=(),
        drift_counts=(),
    ):
        self.run_rows = list(run_rows)
        self.anomaly_cluster_rows = list(anomaly_cluster_rows)
        self.outlier_rows = list(outlier_rows)
        self.drift_rows = list(drift_rows)
        self.drift_counts = list(drift_counts)

    async def execute(self, query, params=None):
        sql = str(query)
        if "FROM meta._ingest_log l" in sql and "LEFT JOIN" in sql:
            return FakeResult(self.run_rows)
        if "GROUP BY source, metric" in sql:
            return FakeResult(self.anomaly_cluster_rows)
        if "row_snapshot" in sql and "ORDER BY z_score" in sql:
            return FakeResult(self.outlier_rows)
        if "FROM meta.schema_drifts ORDER BY first_seen_at" in sql:
            return FakeResult(self.drift_rows)
        if "GROUP BY auto_adapted" in sql:
            return FakeResult(self.drift_counts)
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


def _run_row(**overrides):
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "source": "bom",
        "status": "failed",
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=1),
        "rows_landed": 0,
        "rows_loaded": 0,
        "error_message": "connection timeout",
        "triggered_by": "schedule",
        "anomalies_flagged": 0,
    }
    row.update(overrides)
    return row


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
    session = FakeSession()
    redis = FakeRedis()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis_client] = lambda: redis

    async def noop_recheck_in_background(*args, **kwargs):
        pass

    monkeypatch.setattr(
        data_quality_routes, "run_recheck_in_background", noop_recheck_in_background
    )
    yield session, redis
    app.dependency_overrides.clear()


class TestSummaryEndpoint:
    def test_requires_auth(self, client, wired):
        response = client.get("/v1/data-quality/summary")

        assert response.status_code == 401

    def test_returns_summary_shape(self, client, wired):
        session, _ = wired
        session.run_rows = [_run_row(status="success")]

        response = client.get("/v1/data-quality/summary", headers=_auth("analyst"))

        assert response.status_code == 200
        body = response.json()
        assert "overall" in body
        assert "by_source_24h" in body
        assert len(body["by_source_24h"]) == 5


class TestPublicSummaryEndpoint:
    def test_does_not_require_auth(self, client, wired):
        response = client.get("/v1/data-quality/summary/public")

        assert response.status_code == 200

    def test_returns_only_the_two_aggregate_fields(self, client, wired):
        session, _ = wired
        session.run_rows = [_run_row(status="success")]

        response = client.get("/v1/data-quality/summary/public")

        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {
            "as_of",
            "data_quality_score_pct",
            "open_risks_high_plus",
        }

    def test_open_risks_sums_critical_and_high(self, client, wired):
        session, _ = wired
        # 5 consecutive failures -> "critical"; a shorter streak on a
        # different source -> "high" (see _generate_issues's threshold).
        session.run_rows = [
            _run_row(source="bom", status="failed", started_at=NOW),
            _run_row(
                source="bom", status="failed", started_at=NOW - timedelta(minutes=5)
            ),
            _run_row(
                source="bom", status="failed", started_at=NOW - timedelta(minutes=10)
            ),
            _run_row(
                source="bom", status="failed", started_at=NOW - timedelta(minutes=15)
            ),
            _run_row(
                source="bom", status="failed", started_at=NOW - timedelta(minutes=20)
            ),
        ]

        response = client.get("/v1/data-quality/summary/public")

        assert response.status_code == 200
        assert response.json()["open_risks_high_plus"] == 1

    def test_agrees_with_authenticated_summary(self, client, wired):
        session, _ = wired
        session.run_rows = [_run_row(status="success")]

        full = client.get("/v1/data-quality/summary", headers=_auth("analyst")).json()
        public = client.get("/v1/data-quality/summary/public").json()

        assert public["data_quality_score_pct"] == full["overall"]["pass_rate_pct_24h"]
        assert public["open_risks_high_plus"] == (
            full["by_severity_24h"]["critical"] + full["by_severity_24h"]["high"]
        )


class TestIssuesEndpoint:
    def test_unknown_source_id_is_404(self, client, wired):
        response = client.get(
            "/v1/data-quality/issues?source_id=ds-nonexistent", headers=_auth()
        )

        assert response.status_code == 404

    def test_returns_failure_issues(self, client, wired):
        session, _ = wired
        session.run_rows = [
            _run_row(status="failed", started_at=NOW),
            _run_row(status="failed", started_at=NOW - timedelta(minutes=30)),
        ]

        response = client.get("/v1/data-quality/issues", headers=_auth())

        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["source_id"] == "ds-bom"

    def test_severity_filter(self, client, wired):
        session, _ = wired
        session.run_rows = [_run_row(status="failed")]

        response = client.get(
            "/v1/data-quality/issues?severity=critical", headers=_auth()
        )

        assert response.status_code == 200
        assert response.json()["meta"]["filtered"] == 0


class TestOutliersEndpoint:
    def test_unknown_source_id_is_404(self, client, wired):
        response = client.get(
            "/v1/data-quality/outliers?source_id=ds-nonexistent", headers=_auth()
        )

        assert response.status_code == 404

    def test_returns_outliers(self, client, wired):
        session, _ = wired
        session.outlier_rows = [
            {
                "id": "a1",
                "run_id": "r1",
                "source": "bom",
                "metric": "temp_c",
                "value": 90.0,
                "z_score": 4.2,
                "expected_low": -10.0,
                "expected_high": 55.0,
                "detected_at": NOW,
                "row_snapshot": {"region": "NSW1"},
            }
        ]

        response = client.get("/v1/data-quality/outliers", headers=_auth())

        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["source_id"] == "ds-bom"


class TestSchemaEndpoint:
    def test_returns_schema_report_shape(self, client, wired):
        response = client.get("/v1/data-quality/schema", headers=_auth("analyst"))

        assert response.status_code == 200
        body = response.json()
        assert "drifts" in body
        assert "summary" in body


class TestRecheckEndpoint:
    def test_requires_admin_role(self, client, wired):
        response = client.post(
            "/v1/data-quality/recheck/ds-bom", headers=_auth("analyst")
        )

        assert response.status_code == 403

    def test_unknown_source_is_404(self, client, wired):
        response = client.post(
            "/v1/data-quality/recheck/ds-nonexistent", headers=_auth()
        )

        assert response.status_code == 404

    def test_successful_trigger_returns_202(self, client, wired):
        response = client.post("/v1/data-quality/recheck/ds-bom", headers=_auth())

        assert response.status_code == 202
        body = response.json()
        assert body["source_id"] == "ds-bom"
        assert body["status"] == "queued"
        assert body["recheck_id"].startswith("rc-")

    def test_invalid_window_is_400(self, client, wired):
        response = client.post(
            "/v1/data-quality/recheck/ds-bom",
            json={"window": "P90D"},
            headers=_auth(),
        )

        assert response.status_code == 400

    def test_already_in_progress_is_409(self, client, wired):
        _, redis = wired
        redis.store["dataquality:recheck-lock:ds-bom"] = "1"

        response = client.post("/v1/data-quality/recheck/ds-bom", headers=_auth())

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "recheck_in_progress"

    def test_idempotency_key_replays_the_cached_response(self, client, wired):
        headers = {**_auth(), "Idempotency-Key": "abc-123"}

        first = client.post("/v1/data-quality/recheck/ds-bom", headers=headers)
        second = client.post("/v1/data-quality/recheck/ds-bom", headers=headers)

        assert first.status_code == second.status_code == 202
        assert first.json() == second.json()
