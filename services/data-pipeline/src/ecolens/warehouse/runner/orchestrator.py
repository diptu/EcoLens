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

from ecolens.ingestion.storage.postgres import RawSyncer
from ecolens.shared.observability.logging import get_logger

from .aggregates import AggregateRefresher
from .archive import ArchiveManager
from .dbt_runner import DbtRunner
from .freshness import SourceFreshnessChecker
from .metrics import MetricsEmitter
from .models import RunResult, StageResult
from .quality import DataQualityValidator
from .settings import WarehouseRunnerSettings, get_warehouse_runner_settings

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

        # Stage 1.5: sync MongoDB raw collections -> PostgreSQL raw.*
        # (what dbt actually reads -- freshness above only checks Mongo).
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

        # Stage 6: archive (optional)
        if not skip_archive:
            try:
                self.archiver.connect_mongo()
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
        since = None
        if mode != "full":
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
