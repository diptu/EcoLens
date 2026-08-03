from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ApiError
from app.service import dataquality as dq_service

pytestmark = pytest.mark.anyio

# `get_summary` internally computes its own `datetime.now(UTC)` and buckets
# runs into 24h/7d windows relative to it -- using a fixed historical date
# here would make every run row fall outside those windows. Using "now" at
# import time keeps run rows inside the windows without threading a clock
# fixture through every test.
NOW = datetime.now(UTC)


@pytest.fixture
def anyio_backend():
    return "asyncio"


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
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.queries.append((sql, params))

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
        raise AssertionError(f"unexpected query: {sql}")


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


class TestGenerateIssues:
    async def test_consecutive_failures_produce_one_issue_per_source(self):
        session = FakeSession(
            run_rows=[
                _run_row(started_at=NOW, status="failed"),
                _run_row(started_at=NOW - timedelta(minutes=30), status="failed"),
                _run_row(started_at=NOW - timedelta(minutes=60), status="success"),
            ]
        )

        issues = await dq_service._generate_issues(session)

        failure_issues = [i for i in issues if i["id"] == "dq-failures-ds-bom"]
        assert len(failure_issues) == 1
        assert failure_issues[0]["occurrences"] == 2
        assert failure_issues[0]["category"] == "completeness"
        assert failure_issues[0]["severity"] == "high"

    async def test_five_or_more_consecutive_failures_is_critical(self):
        session = FakeSession(
            run_rows=[
                _run_row(started_at=NOW - timedelta(minutes=30 * i)) for i in range(5)
            ]
        )

        issues = await dq_service._generate_issues(session)

        assert issues[0]["severity"] == "critical"

    async def test_no_failures_produces_no_failure_issue(self):
        session = FakeSession(run_rows=[_run_row(status="success")])

        issues = await dq_service._generate_issues(session)

        assert not any(i["id"].startswith("dq-failures-") for i in issues)

    async def test_anomaly_cluster_becomes_an_issue(self):
        session = FakeSession(
            run_rows=[],
            anomaly_cluster_rows=[
                {
                    "source": "bom",
                    "metric": "temp_c",
                    "occurrences": 4,
                    "first_seen_at": NOW - timedelta(days=1),
                    "last_seen_at": NOW,
                    "avg_score": 0.5,
                    "any_missing": False,
                }
            ],
        )

        issues = await dq_service._generate_issues(session)

        assert len(issues) == 1
        assert issues[0]["id"] == "dq-anomaly-ds-bom-temp_c"
        assert issues[0]["source_id"] == "ds-bom"
        assert issues[0]["category"] == "validity"
        assert issues[0]["auto_resolvable"] is True

    async def test_missing_value_anomaly_cluster_is_completeness(self):
        session = FakeSession(
            run_rows=[],
            anomaly_cluster_rows=[
                {
                    "source": "bom",
                    "metric": "temp_c",
                    "occurrences": 1,
                    "first_seen_at": NOW,
                    "last_seen_at": NOW,
                    "avg_score": 0.5,
                    "any_missing": True,
                }
            ],
        )

        issues = await dq_service._generate_issues(session)

        assert issues[0]["category"] == "completeness"

    async def test_unknown_anomaly_source_is_skipped(self):
        session = FakeSession(
            run_rows=[],
            anomaly_cluster_rows=[
                {
                    "source": "some_unmapped_source",
                    "metric": "x",
                    "occurrences": 1,
                    "first_seen_at": NOW,
                    "last_seen_at": NOW,
                    "avg_score": 0.5,
                    "any_missing": False,
                }
            ],
        )

        issues = await dq_service._generate_issues(session)

        assert issues == []

    async def test_actionable_schema_drift_becomes_an_issue(self):
        session = FakeSession(
            run_rows=[],
            drift_rows=[
                {
                    "id": "d1",
                    "source": "bom",
                    "table_name": "raw.bom_observations",
                    "severity": "high",
                    "kind": "column_removed",
                    "column_name": "cloud_oktas",
                    "old_type": "numeric",
                    "new_type": None,
                    "auto_adapted": False,
                    "action_required": True,
                    "downstream_impact": "Queries will error.",
                    "first_seen_at": NOW,
                    "last_checked_at": NOW,
                }
            ],
        )

        issues = await dq_service._generate_issues(session)

        assert len(issues) == 1
        assert issues[0]["id"] == "dq-schema-d1"
        assert issues[0]["category"] == "consistency"

    async def test_non_actionable_schema_drift_is_skipped(self):
        session = FakeSession(
            run_rows=[],
            drift_rows=[
                {
                    "id": "d2",
                    "source": "bom",
                    "table_name": "raw.bom_observations",
                    "severity": "low",
                    "kind": "column_added",
                    "column_name": "extra",
                    "old_type": None,
                    "new_type": "text",
                    "auto_adapted": True,
                    "action_required": False,
                    "downstream_impact": None,
                    "first_seen_at": NOW,
                    "last_checked_at": NOW,
                }
            ],
        )

        issues = await dq_service._generate_issues(session)

        assert issues == []


class TestGetSummary:
    async def test_counts_failed_and_warned_runs_separately(self):
        session = FakeSession(
            run_rows=[
                _run_row(source="bom", status="failed", anomalies_flagged=0),
                _run_row(source="bom", status="success", anomalies_flagged=3),
                _run_row(source="bom", status="success", anomalies_flagged=0),
            ]
        )
        redis = FakeRedis()

        response = await dq_service.get_summary(session, redis)

        by_bom = next(s for s in response.by_source_24h if s.source_id == "ds-bom")
        assert response.overall.total_tests_24h == 3
        assert response.overall.tests_failed_24h == 1
        assert response.overall.tests_warned_24h == 1
        assert response.overall.tests_passed_24h == 1
        assert by_bom.pass_rate_pct == pytest.approx(33.3, abs=0.1)

    async def test_empty_state_has_none_pass_rate(self):
        session = FakeSession(run_rows=[])
        redis = FakeRedis()

        response = await dq_service.get_summary(session, redis)

        assert response.overall.pass_rate_pct_24h is None
        assert response.overall.total_tests_24h == 0

    async def test_result_is_cached(self):
        session = FakeSession(run_rows=[_run_row(status="success")])
        redis = FakeRedis()

        first = await dq_service.get_summary(session, redis)
        session.run_rows = []  # would change the result if re-queried
        second = await dq_service.get_summary(session, redis)

        assert first == second


class TestListIssues:
    async def test_filters_by_severity_and_paginates(self):
        session = FakeSession(
            run_rows=[
                _run_row(source="bom", status="failed"),
                _run_row(source="openelectricity", status="failed"),
            ]
        )
        redis = FakeRedis()

        response = await dq_service.list_issues(
            session,
            redis,
            source_id=None,
            severity="high",
            category=None,
            status="open",
            limit=50,
            cursor=None,
        )

        assert response.meta.total == 2
        assert response.meta.filtered == 2
        assert all(i.severity == "high" for i in response.data)

    async def test_source_filter_narrows_results(self):
        session = FakeSession(
            run_rows=[
                _run_row(source="bom", status="failed"),
                _run_row(source="openelectricity", status="failed"),
            ]
        )
        redis = FakeRedis()

        response = await dq_service.list_issues(
            session,
            redis,
            source_id="ds-bom",
            severity=None,
            category=None,
            status="open",
            limit=50,
            cursor=None,
        )

        assert response.meta.filtered == 1
        assert response.data[0].source_id == "ds-bom"

    async def test_pagination_sets_has_more_and_next_cursor(self):
        session = FakeSession(
            run_rows=[
                _run_row(source="bom", status="failed"),
                _run_row(source="openelectricity", status="failed"),
            ]
        )
        redis = FakeRedis()

        response = await dq_service.list_issues(
            session,
            redis,
            source_id=None,
            severity=None,
            category=None,
            status="open",
            limit=1,
            cursor=None,
        )

        assert len(response.data) == 1
        assert response.has_more is True
        assert response.next_cursor is not None


class TestListOutliers:
    async def test_maps_anomaly_rows_to_outliers(self):
        session = FakeSession(
            outlier_rows=[
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
                    "row_snapshot": {
                        "region": "NSW1",
                        "station_id": "066062",
                        "ts": "2026-01-01T00:00:00Z",
                    },
                }
            ]
        )
        redis = FakeRedis()

        response = await dq_service.list_outliers(
            session,
            redis,
            source_id=None,
            metric=None,
            z_score_min=3.0,
            from_=NOW - timedelta(days=7),
            to=NOW,
            limit=50,
        )

        assert response.meta.total == 1
        outlier = response.data[0]
        assert outlier.source_id == "ds-bom"
        assert outlier.region == "NSW1"
        assert outlier.station_id == "066062"
        assert outlier.linked_issue_id == "dq-anomaly-ds-bom-temp_c"

    async def test_unknown_source_id_maps_to_a_source_that_matches_nothing(self):
        session = FakeSession(outlier_rows=[])
        redis = FakeRedis()

        response = await dq_service.list_outliers(
            session,
            redis,
            source_id="ds-nonexistent",
            metric=None,
            z_score_min=3.0,
            from_=NOW - timedelta(days=7),
            to=NOW,
            limit=50,
        )

        assert response.data == []
        _, params = session.queries[0]
        assert params["source"] == "__no_such_source__"


class TestGetSchemaReport:
    async def test_maps_drift_rows_and_counts(self):
        session = FakeSession(
            drift_rows=[
                {
                    "id": "d1",
                    "source": "bom",
                    "table_name": "raw.bom_observations",
                    "severity": "high",
                    "kind": "column_removed",
                    "column_name": "cloud_oktas",
                    "old_type": "numeric",
                    "new_type": None,
                    "auto_adapted": False,
                    "action_required": True,
                    "downstream_impact": "Queries will error.",
                    "first_seen_at": NOW,
                    "last_checked_at": NOW,
                }
            ],
            drift_counts=[{"auto_adapted": False, "cnt": 1}],
        )
        redis = FakeRedis()

        response = await dq_service.get_schema_report(session, redis)

        assert len(response.drifts) == 1
        assert response.drifts[0].source_id == "ds-bom"
        assert response.summary.needs_action == 1
        assert response.summary.total_drifts_24h == 1


class TestParseWindow:
    def test_parses_p1d(self):
        assert dq_service._parse_window_to_minutes("P1D") == 1440

    def test_parses_p30d(self):
        assert dq_service._parse_window_to_minutes("P30D") == 43200

    def test_rejects_out_of_range(self):
        with pytest.raises(ApiError) as exc_info:
            dq_service._parse_window_to_minutes("P31D")
        assert exc_info.value.status_code == 400

    def test_rejects_malformed_window(self):
        with pytest.raises(ApiError):
            dq_service._parse_window_to_minutes("1D")


class TestTriggerRecheck:
    async def test_unknown_source_is_404(self):
        redis = FakeRedis()

        with pytest.raises(ApiError) as exc_info:
            await dq_service.trigger_recheck(
                redis,
                "ds-nonexistent",
                ["completeness"],
                "P1D",
                idempotency_key=None,
                triggered_by="diptu",
            )
        assert exc_info.value.status_code == 404

    async def test_successful_trigger_sets_lock_and_returns_queued(self):
        redis = FakeRedis()

        response = await dq_service.trigger_recheck(
            redis,
            "ds-bom",
            ["completeness"],
            "P1D",
            idempotency_key=None,
            triggered_by="diptu",
        )

        assert response.status == "queued"
        assert response.source_id == "ds-bom"
        assert redis.store["dataquality:recheck-lock:ds-bom"] == "1"

    async def test_recheck_already_in_progress_is_409(self):
        redis = FakeRedis()
        redis.store["dataquality:recheck-lock:ds-bom"] = "1"

        with pytest.raises(ApiError) as exc_info:
            await dq_service.trigger_recheck(
                redis,
                "ds-bom",
                ["completeness"],
                "P1D",
                idempotency_key=None,
                triggered_by="diptu",
            )
        assert exc_info.value.status_code == 409

    async def test_idempotency_key_replays_cached_response(self):
        redis = FakeRedis()

        first = await dq_service.trigger_recheck(
            redis,
            "ds-bom",
            ["completeness"],
            "P1D",
            idempotency_key="key-1",
            triggered_by="diptu",
        )
        await redis.delete("dataquality:recheck-lock:ds-bom")
        second = await dq_service.trigger_recheck(
            redis,
            "ds-bom",
            ["completeness"],
            "P1D",
            idempotency_key="key-1",
            triggered_by="diptu",
        )

        assert first == second
