"""Ported from data-pipeline's `tests/test_data_quality_service.py`, the
`_generate_issues`/`get_summary`/`get_public_summary` sections only --
`app.service.dataquality` here only ports the summary path (see that
module's own docstring for what's deliberately excluded)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

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
        drift_rows=(),
    ):
        self.run_rows = list(run_rows)
        self.anomaly_cluster_rows = list(anomaly_cluster_rows)
        self.drift_rows = list(drift_rows)
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.queries.append((sql, params))

        if "FROM meta._ingest_log l" in sql and "LEFT JOIN" in sql:
            return FakeResult(self.run_rows)
        if "GROUP BY source, metric" in sql:
            return FakeResult(self.anomaly_cluster_rows)
        if "FROM meta.schema_drifts ORDER BY first_seen_at" in sql:
            return FakeResult(self.drift_rows)
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


class TestGetPublicSummary:
    async def test_projects_pass_rate_and_high_plus_risk_count(self):
        session = FakeSession(
            run_rows=[_run_row(source="bom", status="failed")] * 5,
        )
        redis = FakeRedis()

        response = await dq_service.get_public_summary(session, redis)

        assert response.data_quality_score_pct == 0.0
        # 5 consecutive failures on one source -> one "critical" issue.
        assert response.open_risks_high_plus == 1

    async def test_reuses_get_summary_so_the_two_never_disagree(self):
        session = FakeSession(run_rows=[_run_row(status="success")])
        redis = FakeRedis()

        full = await dq_service.get_summary(session, redis)
        public = await dq_service.get_public_summary(session, redis)

        assert public.data_quality_score_pct == full.overall.pass_rate_pct_24h
        assert public.as_of == full.as_of
