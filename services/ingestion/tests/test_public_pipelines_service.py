"""Tests for `app.service.public_pipelines` — the `GET /v1/ingestion/
public/{pipelines,runs}` logic (`services/ingestion/TODO.md`'s "Frontend
integration" section)."""

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

    def scalar(self):
        return self._rows[0][0] if self._rows else 0


class FakeSession:
    """Dispatches by a distinguishing SQL substring, same idiom
    `test_ingestion_run_router.py`'s own `FakeSession` uses."""

    def __init__(self, log_rows=None, total=0, filtered=None):
        self.log_rows = log_rows or []
        self.total = total
        self.filtered = filtered if filtered is not None else len(self.log_rows)
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.queries.append((sql, params))

        # Order matters: `_RUN_FROM`'s anomaly-count LEFT JOIN subquery
        # (`count(*) AS cnt FROM meta.anomalies`) means the real row-
        # select query *also* contains the substring "count(*)" -- check
        # the more specific "this is the actual row select" shape first,
        # or it misroutes into the filtered-count branch below.
        if "FROM meta._ingest_log l" in sql and "ORDER BY" in sql:
            return FakeResult(self.log_rows)
        if sql.strip().startswith("SELECT count(*) FROM meta._ingest_log l"):
            return FakeResult([(self.filtered,)])
        if sql.strip() == "SELECT count(*) FROM meta._ingest_log":
            return FakeResult([(self.total,)])
        if "FROM meta._ingest_log" in sql and "started_at >=" in sql:
            return FakeResult(self.log_rows)
        raise AssertionError(f"unexpected query: {sql}")


class TestListPipelinesPublic:
    async def test_returns_all_five_catalog_sources(self):
        session = FakeSession(log_rows=[])

        result = await public_pipelines.list_pipelines_public(session)

        assert result.meta.total == 5
        assert {p.id for p in result.data} == {
            "ds-oe",
            "ds-aemo-nem",
            "ds-aemo-wem",
            "ds-bom",
            "ds-holidays",
        }

    async def test_reports_the_real_unified_beat_cadence_not_catalog_cron(self):
        """`app.models.datasources.CATALOG`'s own `cron` field is `oe`'s
        aspirational 5-min cadence, not what Beat actually dispatches at
        (`*/30 * * * *`, unified since 2026-08-05) -- this must report
        the real one, not the catalog's, per this module's own
        docstring."""
        session = FakeSession(log_rows=[])

        result = await public_pipelines.list_pipelines_public(session)

        oe = next(p for p in result.data if p.id == "ds-oe")
        assert oe.schedule.cron == "*/30 * * * *"

    async def test_a_source_with_no_runs_has_null_stats(self):
        session = FakeSession(log_rows=[])

        result = await public_pipelines.list_pipelines_public(session)

        oe = next(p for p in result.data if p.id == "ds-oe")
        assert oe.run_count_24h == 0
        assert oe.success_rate_24h is None
        assert oe.last_run_at is None

    async def test_computes_success_rate_treating_staged_as_success(self):
        rows = [
            {
                "source": "bom",
                "status": "staged",
                "started_at": NOW,
                "finished_at": NOW + timedelta(seconds=2),
            },
            {
                "source": "bom",
                "status": "success",
                "started_at": NOW - timedelta(minutes=30),
                "finished_at": NOW - timedelta(minutes=30) + timedelta(seconds=2),
            },
            {
                "source": "bom",
                "status": "failed",
                "started_at": NOW - timedelta(hours=1),
                "finished_at": NOW - timedelta(hours=1) + timedelta(seconds=1),
            },
        ]
        session = FakeSession(log_rows=rows)

        result = await public_pipelines.list_pipelines_public(session)

        bom = next(p for p in result.data if p.id == "ds-bom")
        assert bom.run_count_24h == 3
        # 2 of 3 (staged + success) count as non-failures
        assert bom.success_rate_24h == pytest.approx(66.7, abs=0.1)
        assert bom.last_run_at == NOW  # most recent row, DESC order assumed


class TestListRunsPublic:
    async def test_maps_source_to_the_catalog_ds_id(self):
        row = {
            "id": "11111111-1111-1111-1111-111111111111",
            "source": "openelectricity",
            "status": "staged",
            "triggered_by": "schedule",
            "started_at": NOW,
            "finished_at": NOW + timedelta(seconds=1),
            "rows_landed": 24,
            "rows_loaded": None,
            "anomalies_flagged": 0,
        }
        session = FakeSession(log_rows=[row], total=1, filtered=1)

        result = await public_pipelines.list_runs_public(
            session,
            source_id=None,
            status=None,
            trigger=None,
            from_=None,
            to=None,
            limit=100,
            cursor=None,
        )

        assert result.data[0].source_id == "ds-oe"
        assert result.data[0].pipeline_id == "ds-oe"

    async def test_no_error_or_hostname_fields_leak_through(self):
        row = {
            "id": "11111111-1111-1111-1111-111111111111",
            "source": "bom",
            "status": "failed",
            "triggered_by": "manual",
            "started_at": NOW,
            "finished_at": NOW,
            "rows_landed": None,
            "rows_loaded": None,
            "anomalies_flagged": 0,
        }
        session = FakeSession(log_rows=[row], total=1, filtered=1)

        result = await public_pipelines.list_runs_public(
            session,
            source_id=None,
            status=None,
            trigger=None,
            from_=None,
            to=None,
            limit=100,
            cursor=None,
        )

        dumped = result.data[0].model_dump()
        assert "error" not in dumped
        assert "hostname" not in dumped
        assert "metadata" not in dumped

    async def test_duplicates_skipped_is_the_gap_between_landed_and_loaded(self):
        row = {
            "id": "11111111-1111-1111-1111-111111111111",
            "source": "bom",
            "status": "success",
            "triggered_by": "schedule",
            "started_at": NOW,
            "finished_at": NOW + timedelta(seconds=1),
            "rows_landed": 100,
            "rows_loaded": 80,
            "anomalies_flagged": 0,
        }
        session = FakeSession(log_rows=[row], total=1, filtered=1)

        result = await public_pipelines.list_runs_public(
            session,
            source_id=None,
            status=None,
            trigger=None,
            from_=None,
            to=None,
            limit=100,
            cursor=None,
        )

        assert result.data[0].duplicates_skipped == 20

    async def test_has_more_is_false_when_everything_fit_on_one_page(self):
        session = FakeSession(log_rows=[], total=3, filtered=3)

        result = await public_pipelines.list_runs_public(
            session,
            source_id=None,
            status=None,
            trigger=None,
            from_=None,
            to=None,
            limit=100,
            cursor=None,
        )

        assert result.has_more is False
        assert result.next_cursor is None

    async def test_has_more_is_true_and_a_cursor_is_returned_when_more_remain(self):
        session = FakeSession(log_rows=[], total=250, filtered=250)

        result = await public_pipelines.list_runs_public(
            session,
            source_id=None,
            status=None,
            trigger=None,
            from_=None,
            to=None,
            limit=100,
            cursor=None,
        )

        assert result.has_more is True
        assert result.next_cursor is not None

    async def test_source_id_filter_resolves_to_the_registrys_ingest_source(self):
        session = FakeSession(log_rows=[], total=0, filtered=0)

        await public_pipelines.list_runs_public(
            session,
            source_id="ds-aemo-nem",
            status=None,
            trigger=None,
            from_=None,
            to=None,
            limit=100,
            cursor=None,
        )

        filtered_query = next(
            params for sql, params in session.queries if "l.source = :source" in sql
        )
        assert filtered_query["source"] == "aemo_nem"

    async def test_unknown_source_id_filters_to_nothing(self):
        session = FakeSession(log_rows=[], total=0, filtered=0)

        await public_pipelines.list_runs_public(
            session,
            source_id="ds-does-not-exist",
            status=None,
            trigger=None,
            from_=None,
            to=None,
            limit=100,
            cursor=None,
        )

        filtered_query = next(
            params for sql, params in session.queries if "l.source = :source" in sql
        )
        assert filtered_query["source"] == "__no_such_source__"

    async def test_malformed_cursor_falls_back_to_offset_zero(self):
        session = FakeSession(log_rows=[], total=0, filtered=0)

        await public_pipelines.list_runs_public(
            session,
            source_id=None,
            status=None,
            trigger=None,
            from_=None,
            to=None,
            limit=100,
            cursor="not-valid-base64!!!",
        )

        rows_query = next(
            params for sql, params in session.queries if "OFFSET :offset" in sql
        )
        assert rows_query["offset"] == 0
