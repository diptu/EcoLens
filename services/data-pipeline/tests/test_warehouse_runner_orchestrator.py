"""Tests for ecolens.warehouse.runner.orchestrator.WarehouseRunner.

Every stage object is replaced with a mock so these exercise only the
orchestrator's sequencing logic (which stages run, in what order,
what halts the pipeline) -- not any real Mongo/Postgres/dbt behavior,
which is covered by each stage's own test module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ecolens.warehouse.runner.models import StageResult
from ecolens.warehouse.runner.orchestrator import WarehouseRunner
from ecolens.warehouse.runner.settings import WarehouseRunnerSettings


def _stage(name: str, *, success: bool = True, error: str | None = None) -> StageResult:
    now = datetime.now(timezone.utc)
    return StageResult(
        name=name, started_at=now, finished_at=now, success=success, error=error
    )


@pytest.fixture
def runner(tmp_path) -> WarehouseRunner:
    r = WarehouseRunner(WarehouseRunnerSettings(log_dir=tmp_path))

    r.freshness = MagicMock()
    r.freshness.check.return_value = _stage("source_freshness")

    r.raw_syncer = MagicMock()
    r.raw_syncer.connect = AsyncMock()
    r.raw_syncer.sync_all = AsyncMock(return_value={"aemo_nem": 1})
    r.raw_syncer.close = AsyncMock()

    r.dbt = MagicMock()
    r.dbt.run.return_value = _stage("dbt_build")

    r.quality = MagicMock()
    r.quality.connect = AsyncMock()
    r.quality.validate = AsyncMock(return_value=_stage("data_quality"))
    r.quality.close = AsyncMock()

    r.aggregator = MagicMock()
    r.aggregator.connect = AsyncMock()
    r.aggregator.refresh = AsyncMock(return_value=_stage("aggregate_refresh"))
    r.aggregator.close = AsyncMock()

    r.archiver = MagicMock()
    r.archiver.archive.return_value = _stage("archive")
    r.archiver.vacuum.return_value = _stage("vacuum")

    r.metrics = MagicMock()
    r.metrics.emit.return_value = _stage("metrics")

    return r


class TestIncrementalHappyPath:
    @pytest.mark.asyncio
    async def test_runs_all_stages_in_order(self, runner: WarehouseRunner):
        result = await runner.run(mode="incremental")
        names = [s.name for s in result.stages]
        assert names == [
            "source_freshness",
            "raw_sync",
            "dbt_build",
            "data_quality",
            "aggregate_refresh",
            "metrics",
            "archive",
            "vacuum",
        ]
        assert result.success is True

    @pytest.mark.asyncio
    async def test_dbt_run_not_full_refresh(self, runner: WarehouseRunner):
        await runner.run(mode="incremental")
        assert runner.dbt.run.call_args.kwargs["full_refresh"] is False


class TestFullMode:
    @pytest.mark.asyncio
    async def test_dbt_run_uses_full_refresh(self, runner: WarehouseRunner):
        await runner.run(mode="full")
        assert runner.dbt.run.call_args.kwargs["full_refresh"] is True


class TestValidateMode:
    @pytest.mark.asyncio
    async def test_skips_dbt_and_everything_after(self, runner: WarehouseRunner):
        result = await runner.run(mode="validate")
        assert [s.name for s in result.stages] == ["source_freshness"]
        runner.dbt.run.assert_not_called()
        runner.quality.connect.assert_not_called()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_freshness_check_allows_skip(self, runner: WarehouseRunner):
        await runner.run(mode="validate")
        assert runner.freshness.check.call_args.kwargs["allow_skip"] is True

    @pytest.mark.asyncio
    async def test_still_emits_metrics(self, runner: WarehouseRunner):
        await runner.run(mode="validate")
        runner.metrics.emit.assert_called_once()


class TestStageFailureHaltsPipeline:
    @pytest.mark.asyncio
    async def test_freshness_failure_stops_before_dbt(self, runner: WarehouseRunner):
        runner.freshness.check.return_value = _stage(
            "source_freshness", success=False, error="stale"
        )
        result = await runner.run(mode="incremental")
        assert [s.name for s in result.stages] == ["source_freshness"]
        assert result.success is False
        runner.dbt.run.assert_not_called()
        runner.metrics.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_dbt_failure_stops_before_quality(self, runner: WarehouseRunner):
        runner.dbt.run.return_value = _stage(
            "dbt_build", success=False, error="dbt exited 1"
        )
        result = await runner.run(mode="incremental")
        assert [s.name for s in result.stages] == [
            "source_freshness",
            "raw_sync",
            "dbt_build",
        ]
        assert result.success is False
        runner.quality.connect.assert_not_called()
        runner.metrics.emit.assert_called_once()


class TestQualityViolationsDoNotHaltPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_continues_after_quality_violations(
        self, runner: WarehouseRunner
    ):
        runner.quality.validate = AsyncMock(
            return_value=_stage("data_quality", success=False, error="3 violations")
        )
        result = await runner.run(mode="incremental")
        names = [s.name for s in result.stages]
        assert "aggregate_refresh" in names
        assert "archive" in names
        # Overall run is marked unsuccessful (violations are surfaced,
        # just not treated as a hard abort).
        assert result.success is False


class TestSkipFlags:
    @pytest.mark.asyncio
    async def test_skip_aggregates(self, runner: WarehouseRunner):
        result = await runner.run(mode="incremental", skip_aggregates=True)
        assert "aggregate_refresh" not in [s.name for s in result.stages]
        runner.aggregator.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_archive(self, runner: WarehouseRunner):
        result = await runner.run(mode="incremental", skip_archive=True)
        names = [s.name for s in result.stages]
        assert "archive" not in names
        assert "vacuum" not in names
        runner.archiver.archive.assert_not_called()


class TestDbtSelectExclude:
    @pytest.mark.asyncio
    async def test_select_and_exclude_forwarded(self, runner: WarehouseRunner):
        await runner.run(
            mode="incremental", dbt_select=["tag:ml_features"], dbt_exclude=["tag:dev"]
        )
        assert runner.dbt.run.call_args.kwargs["select"] == ["tag:ml_features"]
        assert runner.dbt.run.call_args.kwargs["exclude"] == ["tag:dev"]
