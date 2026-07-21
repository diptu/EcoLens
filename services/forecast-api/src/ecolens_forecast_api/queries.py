"""The one query this service issues.

Reads exactly the columns the baseline forecaster needs from
`ml_features_demand_v1` -- the warehouse mart already carries 48
lagged demand values, a 7-day rolling mean/stddev, weather, and the
holiday flag on one row per `(region, ts_30)` (see
`warehouse/werehouse.md` and `warehouse/dbt_project/models/marts/
ml_features_demand_v1.sql` in data-pipeline). No joins: a single
`WHERE region = $1 ORDER BY ts_30 DESC LIMIT 1` against one table.
"""

from __future__ import annotations

from typing import Any

from .db import ConnectionPool

_LAG_COLUMNS = [f"demand_lag_{i:02d}" for i in range(1, 49)]

_FEATURE_COLUMNS = [
    "ts_30",
    "demand_mw",
    *_LAG_COLUMNS,
    "demand_rolling_avg_7d",
    "demand_rolling_std_7d",
]

_LATEST_FEATURE_ROW_QUERY = (
    f"SELECT {', '.join(_FEATURE_COLUMNS)} "  # nosec B608 - fixed literal column list, not user input
    "FROM ml_features_demand_v1 "
    "WHERE region = $1 "
    "ORDER BY ts_30 DESC "
    "LIMIT 1"
)


async def get_latest_feature_row(
    pool: ConnectionPool, region: str
) -> dict[str, Any] | None:
    """Most recent feature row for `region`, or None if the mart has no data yet."""
    return await pool.fetchrow(_LATEST_FEATURE_ROW_QUERY, region)


__all__ = ["get_latest_feature_row"]
