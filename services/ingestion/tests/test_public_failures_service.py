"""Tests for `app.service.public_pipelines`'s `list_failed_public`/
`list_retry_queue_public`/`get_scheduler_status_public` — the `GET
/v1/ingestion/public/{failed,retry-queue,scheduler}` logic added for the
dashboard's cutover off `data-pipeline` (`lib/ingestion.ts`'s module
docstring)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.service import public_pipelines

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]

    def scalar(self):
        return self._rows[0][0] if self._rows else 0


class FakeSession:
    """Dispatches by a distinguishing SQL substring, same idiom
    `test_public_pipelines_service.py`'s own `FakeSession` uses."""

    def __init__(
        self,
        failed_rows=None,
        sync_failed_rows=None,
        failed_counts=None,
        sync_failed_size=None,
        failed_total=0,
        queue_depth=0,
        scheduled_recent_count=0,
        recent_runs=None,
    ):
        self.failed_rows = failed_rows or []
        self.sync_failed_rows = sync_failed_rows or []
        self.failed_counts = failed_counts or {"failed_24h": 0, "failed_7d": 0}
        self.sync_failed_size = sync_failed_size or {"cnt": 0, "oldest": None}
        self.failed_total = failed_total
        self.queue_depth = queue_depth
        self.scheduled_recent_count = scheduled_recent_count
        self.recent_runs = recent_runs or []
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.queries.append((sql, params))

        if "failed_24h" in sql:
            return FakeResult([self.failed_counts])
        if sql.strip() == "SELECT count(*) FROM meta._ingest_log WHERE status = 'failed'":
            return FakeResult([(self.failed_total,)])
        if "status = 'failed'" in sql and "ORDER BY" in sql:
            return FakeResult(self.failed_rows)
        if "status = 'sync_failed'" in sql and "ORDER BY" in sql:
            return FakeResult(self.sync_failed_rows)
        if "min(finished_at)" in sql:
            return FakeResult([self.sync_failed_size])
        if "status IN ('running', 'staged')" in sql:
            return FakeResult([(self.queue_depth,)])
        if "triggered_by = 'schedule'" in sql:
            return FakeResult([(self.scheduled_recent_count,)])
        if "ORDER BY started_at DESC LIMIT 10" in sql:
            return FakeResult(self.recent_runs)
        raise AssertionError(f"unexpected query: {sql}")


class TestListFailedPublic:
    async def test_returns_empty_when_no_failures(self):
        session = FakeSession()

        result = await public_pipelines.list_failed_public(session, limit=50, cursor=None)

        assert result.data == []
        assert result.meta.total_failed_24h == 0
        assert result.has_more is False

    async def test_classifies_and_redacts_errors(self):
        session = FakeSession(
            failed_rows=[
                {
                    "id": "run-1",
                    "source": "openelectricity",
                    "status": "failed",
                    "started_at": NOW,
                    "finished_at": NOW + timedelta(seconds=5),
                    "error_message": "OpenElectricityError: Unauthorized -- api_key: sk-real-secret-value invalid",
                }
            ],
            failed_counts={"failed_24h": 1, "failed_7d": 1},
            failed_total=1,
        )

        result = await public_pipelines.list_failed_public(session, limit=50, cursor=None)

        assert len(result.data) == 1
        item = result.data[0]
        assert item.pipeline_id == "ds-oe"
        assert item.source_id == "ds-oe"
        assert item.duration_ms == 5000
        assert item.error.code == "missing_credentials"
        assert "sk-real-secret-value" not in item.error.message
        assert "[redacted]" in item.error.message
        assert item.error.retryable is False
        assert item.can_retry_now is False

    async def test_unclassified_retryable_error_stays_retryable(self):
        session = FakeSession(
            failed_rows=[
                {
                    "id": "run-2",
                    "source": "bom",
                    "status": "failed",
                    "started_at": NOW,
                    "finished_at": None,
                    "error_message": "connection reset by peer",
                }
            ],
            failed_counts={"failed_24h": 1, "failed_7d": 1},
            failed_total=1,
        )

        result = await public_pipelines.list_failed_public(session, limit=50, cursor=None)

        item = result.data[0]
        assert item.error.code is None
        assert item.error.retryable is True
        assert item.can_retry_now is True
        assert item.duration_ms is None


class TestListRetryQueuePublic:
    async def test_returns_empty_when_nothing_queued(self):
        session = FakeSession()

        result = await public_pipelines.list_retry_queue_public(session, limit=50)

        assert result.data == []
        assert result.meta.queue_size == 0

    async def test_maps_sync_failed_rows_to_queue_items(self):
        session = FakeSession(
            sync_failed_rows=[
                {
                    "id": "run-3",
                    "source": "aemo_nem",
                    "status": "sync_failed",
                    "started_at": NOW,
                    "finished_at": NOW + timedelta(seconds=2),
                    "error_message": "duplicate key value violates unique constraint",
                }
            ],
            sync_failed_size={"cnt": 1, "oldest": NOW + timedelta(seconds=2)},
        )

        result = await public_pipelines.list_retry_queue_public(session, limit=50)

        assert len(result.data) == 1
        item = result.data[0]
        assert item.queue_id == "rq-run-3"
        assert item.pipeline_id == "ds-aemo-nem"
        assert item.backoff_strategy == "manual"
        assert item.retry_count == 0
        assert item.next_retry_at is None
        assert result.meta.queue_size == 1


class TestGetSchedulerStatusPublic:
    async def test_reports_all_5_sources_as_upcoming(self):
        session = FakeSession()

        result = await public_pipelines.get_scheduler_status_public(session)

        assert {u.pipeline_id for u in result.upcoming_runs} == {
            "ds-oe",
            "ds-aemo-nem",
            "ds-aemo-wem",
            "ds-bom",
            "ds-holidays",
        }
        assert all(u.trigger == "schedule" for u in result.upcoming_runs)

    async def test_reports_queue_depth_from_shared_ingest_log(self):
        session = FakeSession(queue_depth=3)

        result = await public_pipelines.get_scheduler_status_public(session)

        assert result.scheduler.queue_depth == 3

    async def test_worker_alive_when_a_recent_scheduled_run_exists(self):
        session = FakeSession(scheduled_recent_count=2)

        result = await public_pipelines.get_scheduler_status_public(session)

        assert result.scheduler.active_workers == 1
        assert result.scheduler.total_workers == 1

    async def test_worker_reported_dead_with_no_recent_scheduled_run(self):
        session = FakeSession(scheduled_recent_count=0)

        result = await public_pipelines.get_scheduler_status_public(session)

        assert result.scheduler.active_workers == 0

    async def test_recent_runs_included(self):
        session = FakeSession(
            recent_runs=[
                {
                    "id": "run-4",
                    "source": "bom",
                    "status": "success",
                    "started_at": NOW,
                    "finished_at": NOW + timedelta(seconds=1),
                }
            ]
        )

        result = await public_pipelines.get_scheduler_status_public(session)

        assert len(result.recent_runs) == 1
        assert result.recent_runs[0].pipeline_id == "ds-bom"
        assert result.recent_runs[0].duration_ms == 1000
