"""Orchestrates all 7 stages in order.

Stages run sequentially; failure of a required stage (freshness, raw
sync, dbt) halts the pipeline — subsequent stages don't run.
Data-quality violations are warnings, not failures (logged to the run
so they can be alerted on later, but they don't block the pipeline).
Metrics always emit, even on early-abort, so there's a record of what
happened.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ecolens.ingestion.repository.raw_sync import RawSyncer
from ecolens.shared.observability.logging import get_logger

from .aggregates import AggregateRefresher
from .archive import ArchiveManager
from .dbt_runner import DbtRunner
from .freshness import SourceFreshnessChecker
from .metrics import MetricsEmitter
from ecolens.warehouse.models.run_result import RunResult, StageResult
from .quality import DataQualityValidator
from ecolens.warehouse.core.runner_settings import (
    WarehouseRunnerSettings,
    get_warehouse_runner_settings,
)

log = get_logger(__name__)


class WarehouseRunner:
    """Orchestrates all 7 stages in order."""

    def __init__(self, settings: WarehouseRunnerSettings | None = None) -> None:
        self.settings = settings or get_warehouse_runner_settings()
        self.freshness = SourceFreshnessChecker(self.settings)
        self.raw_syncer = RawSyncer(pg_settings=self.settings)
        self.dbt = DbtRunner(self.settings)
        self.quality = DataQualityValidator(self.settings)
        self.aggregator = AggregateRefresher(self.settings)
        self.metrics = MetricsEmitter(self.settings)
        self.archiver = ArchiveManager(self.settings)

    async def run(
        self,
        *,
        mode: str = "incremental",  # "incremental" | "full" | "validate"
        dbt_select: list[str] | None = None,
        dbt_exclude: list[str] | None = None,
        skip_aggregates: bool = False,
        skip_archive: bool = False,
    ) -> RunResult:
        started = datetime.now(timezone.utc)
        log.info("runner.start", mode=mode, select=dbt_select, exclude=dbt_exclude)
        result = RunResult(started_at=started, finished_at=started, success=True)

        # Stage 1: source freshness (always)
        try:
            self.freshness.connect()
            r = self.freshness.check(allow_skip=(mode == "validate"))
            result.stages.append(r)
            if not r.success:
                result.success = False
                result.finished_at = datetime.now(timezone.utc)
                self.metrics.emit(result)
                return result
        finally:
            self.freshness.close()

        if mode == "validate":
            result.finished_at = datetime.now(timezone.utc)
            result.success = True
            self.metrics.emit(result)
            return result

        # Stage 1.5: sync DuckDB raw tables -> PostgreSQL raw.*
        # (what dbt actually reads -- freshness above only checks DuckDB).
        r = await self._run_raw_sync(mode)
        result.stages.append(r)
        if not r.success:
            result.success = False
            result.finished_at = datetime.now(timezone.utc)
            self.metrics.emit(result)
            return result

        # Stage 2: dbt run
        r = self.dbt.run(
            command="build",
            select=dbt_select,
            exclude=dbt_exclude,
            full_refresh=(mode == "full"),
        )
        result.stages.append(r)
        if not r.success:
            result.success = False
            result.finished_at = datetime.now(timezone.utc)
            self.metrics.emit(result)
            return result

        # Stage 3: data quality (violations are warnings, not failures)
        try:
            await self.quality.connect()
            result.stages.append(await self.quality.validate())
        finally:
            await self.quality.close()

        # Stage 4: aggregate refresh (optional)
        if not skip_aggregates:
            try:
                await self.aggregator.connect()
                result.stages.append(await self.aggregator.refresh())
            finally:
                await self.aggregator.close()

        # Stage 5: metrics (always)
        result.finished_at = datetime.now(timezone.utc)
        result.success = all(s.success for s in result.stages)
        result.stages.append(self.metrics.emit(result))

        # Stage 6: archive (no-op, see archive.py) + vacuum (optional)
        if not skip_archive:
            try:
                self.archiver.connect_pg()
                result.stages.append(self.archiver.archive())
                result.stages.append(self.archiver.vacuum())
            finally:
                self.archiver.close()

        log.info(
            "runner.complete",
            success=result.success,
            duration_s=round(result.duration_seconds, 1),
            stages=len(result.stages),
        )
        return result

    async def _run_raw_sync(self, mode: str) -> StageResult:
        started = datetime.now(timezone.utc)
        # "full" here means "dbt --full-refresh" (rebuild derived models
        # from scratch using whatever's currently in raw.*) -- it does
        # NOT mean "resync DuckDB's entire unbounded history into raw.*
        # again". raw.* is a bounded working copy that ongoing
        # incremental runs + archive()'s retention trim already keep
        # populated for the last settings.raw_retention_days, so full
        # mode uses the same tight, cheap `raw_sync_lookback_days` window
        # as incremental mode to pick up any last-minute rows, rather
        # than a wider one.
        #
        # This can't simply be widened to raw_retention_days instead:
        # `since` bounds RawSyncer.sync_one by `fetched_at` (ingestion
        # time), not by the rows' own `ts` (event time) -- a wider,
        # fetched_at-based window doesn't reliably bound how much
        # *event-time* history gets synced (a single bulk historical
        # backfill can stamp a huge ts range with one recent fetched_at,
        # which is exactly what blew NeonDB's 512MB cap when this was
        # tried, see TODO.md). A genuine unbounded raw.* backfill (e.g.
        # after rotating to a fresh Neon project) is a deliberate
        # one-off -- use scripts/sync_raw.py --full directly, not this
        # cron-safe runner path.
        since = datetime.now(timezone.utc) - timedelta(
            days=self.settings.raw_sync_lookback_days
        )
        try:
            await self.raw_syncer.connect()
            synced = await self.raw_syncer.sync_all(since=since)
        except Exception as exc:  # noqa: BLE001
            return StageResult(
                name="raw_sync",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=False,
                error=f"raw sync failed: {exc}",
            )
        finally:
            await self.raw_syncer.close()
        finished = datetime.now(timezone.utc)
        return StageResult(
            name="raw_sync",
            started_at=started,
            finished_at=finished,
            success=True,
            rows_affected=sum(synced.values()),
            metrics={"sources": synced},
        )


__all__ = ["WarehouseRunner"]
