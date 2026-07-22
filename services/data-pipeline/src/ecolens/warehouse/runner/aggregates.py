"""Stage 4: refresh materialized views / rollups in the warehouse.

A separate stage so the dashboard's "national summary" endpoint
doesn't have to recompute aggregates on every request.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import asyncpg

from ecolens.shared.observability.logging import get_logger

from .models import StageResult
from .settings import WarehouseRunnerSettings

log = get_logger(__name__)

VIEWS: list[str] = [
    "mv_daily_national_demand",  # 1 row per day per region
    "mv_regional_generation_share",  # renewable_proportion per day per region
    "mv_weekly_demand_summary",  # 1 row per week
]


class AggregateRefresher:
    """Refreshes materialized views / rollups in the warehouse."""

    def __init__(self, settings: WarehouseRunnerSettings) -> None:
        self.settings = settings
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self.settings.pg_dsn:
            self._pool = await asyncpg.create_pool(
                dsn=self.settings.pg_dsn, min_size=1, max_size=2
            )
        else:
            self._pool = await asyncpg.create_pool(
                host=self.settings.pg_host,
                port=self.settings.pg_port,
                database=self.settings.pg_database,
                user=self.settings.pg_user,
                password=self.settings.pg_password,
                min_size=1,
                max_size=2,
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def refresh(self) -> StageResult:
        started = datetime.now(timezone.utc)
        if self._pool is None:
            return StageResult(
                name="aggregate_refresh",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=True,
                metrics={"status": "skipped", "reason": "not connected"},
            )
        refreshed: list[dict[str, Any]] = []
        try:
            async with self._pool.acquire() as conn:
                for view in VIEWS:
                    exists = await conn.fetchval(
                        "SELECT 1 FROM pg_matviews WHERE matviewname = $1", view
                    )
                    if not exists:
                        log.info(
                            "aggregate_refresh.skip", view=view, reason="not found"
                        )
                        continue
                    t0 = time.perf_counter()
                    await conn.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")
                    latency = round((time.perf_counter() - t0) * 1000, 1)
                    refreshed.append({"view": view, "latency_ms": latency})
                    log.info("aggregate_refresh.view", view=view, latency_ms=latency)
        except Exception as exc:  # noqa: BLE001
            return StageResult(
                name="aggregate_refresh",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=False,
                error=f"refresh failed: {exc}",
            )
        finished = datetime.now(timezone.utc)
        return StageResult(
            name="aggregate_refresh",
            started_at=started,
            finished_at=finished,
            success=True,
            rows_affected=len(refreshed),
            metrics={"refreshed": refreshed},
        )


__all__ = ["AggregateRefresher", "VIEWS"]
