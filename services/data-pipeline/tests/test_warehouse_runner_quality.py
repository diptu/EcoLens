"""Tests for ecolens.warehouse.runner.quality.DataQualityValidator.

Uses the shared FakeAsyncpgConn/FakeAsyncpgPool doubles (conftest.py)
so these never touch a real PostgreSQL server. `_check_freshness` /
`_check_null_rates` / `_check_gaps` are tested directly since each
issues a fixed, ordered sequence of `fetchrow` calls that's easy to
script with a queue-based fake -- driving the same scenarios through
the full `validate()` would require interleaving all three queues.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from conftest import FakeAsyncpgConn, FakeAsyncpgPool
from ecolens.warehouse.runner.quality import DataQualityValidator
from ecolens.warehouse.runner.settings import WarehouseRunnerSettings

NOW = datetime.now(timezone.utc)


@pytest.fixture
def validator() -> DataQualityValidator:
    return DataQualityValidator(WarehouseRunnerSettings())


class TestNotConnected:
    @pytest.mark.asyncio
    async def test_validate_skips_when_not_connected(
        self, validator: DataQualityValidator
    ):
        result = await validator.validate()
        assert result.success is True
        assert result.metrics.get("status") == "skipped"


class TestCheckFreshness:
    @pytest.mark.asyncio
    async def test_all_tables_fresh_yields_no_violations(
        self, validator: DataQualityValidator
    ):
        # 4 tables in FRESHNESS_CHECKS order, all with a recent latest ts.
        conn = FakeAsyncpgConn(fetchrow_results=[{"latest": NOW, "n": 100}] * 4)
        violations = await validator._check_freshness(conn)
        assert violations == []

    @pytest.mark.asyncio
    async def test_stale_table_reported(self, validator: DataQualityValidator):
        stale = NOW - timedelta(hours=5)
        conn = FakeAsyncpgConn(
            fetchrow_results=[
                {"latest": NOW, "n": 100},
                {"latest": NOW, "n": 100},
                {"latest": stale, "n": 100},  # ml_features_demand_v1 -- 45min threshold
                {"latest": NOW, "n": 100},
            ]
        )
        violations = await validator._check_freshness(conn)
        assert len(violations) == 1
        assert violations[0]["type"] == "stale_table"
        assert violations[0]["table"] == "ml_features_demand_v1"

    @pytest.mark.asyncio
    async def test_empty_table_reported(self, validator: DataQualityValidator):
        conn = FakeAsyncpgConn(
            fetchrow_results=[
                {"latest": NOW, "n": 0},
                {"latest": NOW, "n": 100},
                {"latest": NOW, "n": 100},
                {"latest": NOW, "n": 100},
            ]
        )
        violations = await validator._check_freshness(conn)
        assert violations[0]["type"] == "empty_table"
        assert violations[0]["table"] == "fact_demand_30min"

    @pytest.mark.asyncio
    async def test_no_row_reported_as_empty_table(
        self, validator: DataQualityValidator
    ):
        conn = FakeAsyncpgConn(fetchrow_results=[None, None, None, None])
        violations = await validator._check_freshness(conn)
        assert len(violations) == 4
        assert all(v["type"] == "empty_table" for v in violations)


class TestCheckNullRates:
    @pytest.mark.asyncio
    async def test_within_threshold_yields_no_violations(
        self, validator: DataQualityValidator
    ):
        # 5 columns in NULL_CHECKS order, all well within their max_pct.
        conn = FakeAsyncpgConn(fetchrow_results=[{"n": 1000, "null_n": 0}] * 5)
        violations = await validator._check_null_rates(conn)
        assert violations == []

    @pytest.mark.asyncio
    async def test_high_null_rate_reported(self, validator: DataQualityValidator):
        conn = FakeAsyncpgConn(
            fetchrow_results=[
                {"n": 1000, "null_n": 100},  # demand_mw: 10% > 5% max -> violation
                {"n": 1000, "null_n": 0},
                {"n": 1000, "null_n": 0},
                {"n": 1000, "null_n": 0},
                {"n": 1000, "null_n": 0},
            ]
        )
        violations = await validator._check_null_rates(conn)
        assert len(violations) == 1
        assert violations[0]["type"] == "high_null_rate"
        assert violations[0]["column"] == "demand_mw"

    @pytest.mark.asyncio
    async def test_zero_rows_is_skipped_not_a_violation(
        self, validator: DataQualityValidator
    ):
        conn = FakeAsyncpgConn(fetchrow_results=[{"n": 0, "null_n": 0}] * 5)
        violations = await validator._check_null_rates(conn)
        assert violations == []


class TestCheckGaps:
    @pytest.mark.asyncio
    async def test_no_gap_within_tolerance(self, validator: DataQualityValidator):
        conn = FakeAsyncpgConn(
            fetchrow_results=[
                {"region": "NSW1", "span": timedelta(hours=23.5), "n": 48}
            ]
        )
        violations = await validator._check_gaps(conn)
        assert violations == []

    @pytest.mark.asyncio
    async def test_gap_over_tolerance_reported(self, validator: DataQualityValidator):
        # 24h span -> 48 expected slots, only 40 rows -> 8 missing (> 3 slots default).
        conn = FakeAsyncpgConn(
            fetchrow_results=[{"region": "NSW1", "span": timedelta(hours=24), "n": 40}]
        )
        violations = await validator._check_gaps(conn)
        assert len(violations) == 1
        assert violations[0]["type"] == "time_series_gaps"
        assert violations[0]["gaps"][0]["missing_slots"] == 8

    @pytest.mark.asyncio
    async def test_gap_tolerance_derived_from_settings(self):
        # max_consecutive_gap_minutes=180 -> 6 slots tolerance; 4 missing should pass.
        validator = DataQualityValidator(
            WarehouseRunnerSettings(max_consecutive_gap_minutes=180)
        )
        conn = FakeAsyncpgConn(
            fetchrow_results=[{"region": "NSW1", "span": timedelta(hours=24), "n": 44}]
        )
        violations = await validator._check_gaps(conn)
        assert violations == []

    @pytest.mark.asyncio
    async def test_no_row_yields_no_violations(self, validator: DataQualityValidator):
        conn = FakeAsyncpgConn(fetchrow_results=[None])
        violations = await validator._check_gaps(conn)
        assert violations == []


class TestValidateIntegration:
    @pytest.mark.asyncio
    async def test_query_error_returns_failed_stage(
        self, validator: DataQualityValidator
    ):
        validator._pool = FakeAsyncpgPool(FakeAsyncpgConn(raises=RuntimeError("boom")))
        result = await validator.validate()
        assert result.success is False
        assert "boom" in (result.error or "")
