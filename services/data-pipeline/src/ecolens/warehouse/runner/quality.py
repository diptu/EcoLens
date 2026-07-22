"""Stage 3: post-dbt data quality validation.

Runs SQL queries against the warehouse to detect:
  - Stale fact tables (latest ts > threshold)
  - High null rates on critical columns
  - Gaps in time-series (no row for > 90 min)
  - Empty tables
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from ecolens.shared.observability.logging import get_logger

from .models import StageResult
from .settings import WarehouseRunnerSettings

log = get_logger(__name__)

# (table, latest_ts_column, threshold)
FRESHNESS_CHECKS: list[tuple[str, str, timedelta]] = [
    ("fact_demand_30min", "ts_30", timedelta(minutes=45)),
    ("fact_generation_30min", "ts_30", timedelta(minutes=45)),
    ("ml_features_demand_v1", "ts_30", timedelta(minutes=45)),
    ("dim_holiday", "date", timedelta(days=30)),
]

# (table, column, max_null_pct)
NULL_CHECKS: list[tuple[str, str, float]] = [
    ("fact_demand_30min", "demand_mw", 0.05),
    ("fact_demand_30min", "temp_c", 0.15),  # some missing is OK
    ("fact_demand_30min", "is_holiday", 0.0),  # never null
    ("fact_demand_30min", "renewable_proportion", 0.10),
    ("fact_demand_30min", "emissions_intensity_kgco2e_per_mwh", 0.10),
]


class DataQualityValidator:
    """Post-dbt checks that the warehouse is actually serving clean data."""

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

    async def validate(self) -> StageResult:
        started = datetime.now(timezone.utc)
        if self._pool is None:
            return StageResult(
                name="data_quality",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=True,
                metrics={"status": "skipped", "reason": "not connected"},
            )
        violations: list[dict[str, Any]] = []
        try:
            async with self._pool.acquire() as conn:
                violations.extend(await self._check_freshness(conn))
                violations.extend(await self._check_null_rates(conn))
                violations.extend(await self._check_gaps(conn))
        except Exception as exc:  # noqa: BLE001
            return StageResult(
                name="data_quality",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=False,
                error=f"validation query failed: {exc}",
            )
        finished = datetime.now(timezone.utc)
        success = len(violations) == 0
        log.info("data_quality.validate", violations=len(violations), success=success)
        return StageResult(
            name="data_quality",
            started_at=started,
            finished_at=finished,
            success=success,
            metrics={"violations": violations, "violation_count": len(violations)},
            error=None if success else f"{len(violations)} quality violations",
        )

    async def _check_freshness(self, conn: Any) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        for table, ts_col, threshold in FRESHNESS_CHECKS:
            # table/ts_col come only from the hardcoded FRESHNESS_CHECKS
            # constant above, never from request input; Postgres
            # identifiers can't be bound as query parameters.
            query = f"SELECT MAX({ts_col}) AS latest, COUNT(*) AS n FROM {table}"  # nosec B608
            row = await conn.fetchrow(query)
            if row is None or row["n"] == 0:
                violations.append({"type": "empty_table", "table": table})
                continue
            latest = row["latest"]
            if latest is None:
                violations.append({"type": "no_latest_ts", "table": table})
                continue
            if not isinstance(latest, datetime):
                # dim_holiday's check column is a plain `date` (no
                # tzinfo attribute at all, unlike the timestamptz
                # columns every other table here is checked on).
                latest = datetime(
                    latest.year, latest.month, latest.day, tzinfo=timezone.utc
                )
            elif latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - latest
            if age > threshold:
                violations.append(
                    {
                        "type": "stale_table",
                        "table": table,
                        "latest_ts": latest.isoformat(),
                        "age_minutes": round(age.total_seconds() / 60, 1),
                        "threshold_minutes": round(threshold.total_seconds() / 60, 1),
                    }
                )
        return violations

    async def _check_null_rates(self, conn: Any) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        for table, col, max_pct in NULL_CHECKS:
            # table/col come only from the hardcoded NULL_CHECKS constant
            # above, never from request input.
            query = (
                f"SELECT COUNT(*) AS n, "  # nosec B608
                f"COUNT(*) FILTER (WHERE {col} IS NULL) AS null_n "
                f"FROM {table} WHERE ts_30 >= NOW() - INTERVAL '7 days'"
            )
            row = await conn.fetchrow(query)
            if row is None or row["n"] == 0:
                continue
            null_pct = row["null_n"] / row["n"]
            if null_pct > max_pct:
                violations.append(
                    {
                        "type": "high_null_rate",
                        "table": table,
                        "column": col,
                        "null_pct": round(null_pct, 3),
                        "max_pct": max_pct,
                        "sample_size": row["n"],
                    }
                )
        return violations

    async def _check_gaps(self, conn: Any) -> list[dict[str, Any]]:
        row = await conn.fetchrow(
            "SELECT region, MAX(ts_30) - MIN(ts_30) AS span, COUNT(*) AS n "
            "FROM fact_demand_30min "
            "WHERE ts_30 >= NOW() - INTERVAL '24 hours' "
            "GROUP BY region"
        )
        max_gap_slots = self.settings.max_consecutive_gap_minutes // 30
        gaps: list[dict[str, Any]] = []
        if row:
            expected = int(row["span"].total_seconds() / 1800)  # 30-min slots
            if expected - row["n"] > max_gap_slots:
                gaps.append(
                    {
                        "region": row["region"],
                        "expected_slots": expected,
                        "actual_rows": row["n"],
                        "missing_slots": expected - row["n"],
                    }
                )
        return [{"type": "time_series_gaps", "gaps": gaps}] if gaps else []


__all__ = ["DataQualityValidator", "FRESHNESS_CHECKS", "NULL_CHECKS"]
