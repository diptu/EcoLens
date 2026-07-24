"""The queries this service issues against `ml_features_demand_v1`.

`get_latest_feature_row`: what the baseline forecaster needs -- the
mart already carries 48 lagged demand values, a 7-day rolling mean/
stddev, weather, and the holiday flag on one row per `(region, ts_30)`
(see `warehouse/werehouse.md` and `warehouse/dbt_project/models/marts/
ml_features_demand_v1.sql` in data-pipeline). No joins: a single
`WHERE region = $1 ORDER BY ts_30 DESC LIMIT 1` against one table.

`get_recent_feature_rows`: what the real LSTM needs (ECO-F05/F06) --
the last `lookback` rows of raw covariates, chronologically ascending,
to reconstruct the same `(lookback, n_features)` window shape
`data-pipeline`'s `forecasting/features.py`/`serving/forecast.py` build
at training/batch-eval time.
"""

from __future__ import annotations

from typing import Any

from .db import ConnectionPool
from .forecasting.features import FEATURE_COLUMNS

_LAG_COLUMNS = [f"demand_lag_{i:02d}" for i in range(1, 49)]

_BASELINE_FEATURE_COLUMNS = [
    "ts_30",
    "demand_mw",
    *_LAG_COLUMNS,
    "demand_rolling_avg_7d",
    "demand_rolling_std_7d",
]

_LATEST_FEATURE_ROW_QUERY = (
    f"SELECT {', '.join(_BASELINE_FEATURE_COLUMNS)} "  # nosec B608 - fixed literal column list, not user input
    "FROM ml_features_demand_v1 "
    "WHERE region = $1 "
    "ORDER BY ts_30 DESC "
    "LIMIT 1"
)

# $2 (lookback) is a bind parameter, not string-interpolated -- the
# LIMIT here bounds a subquery so the final result stays chronologically
# ascending (oldest first, what build_window expects) without a second
# in-Python reverse.
_RECENT_FEATURE_ROWS_QUERY = (
    f"SELECT ts_30, {', '.join(FEATURE_COLUMNS)} "  # nosec B608 - fixed literal column list, not user input
    "FROM ("
    "  SELECT ts_30, " + ", ".join(FEATURE_COLUMNS) + " "  # nosec B608 - same fixed column list
    "  FROM ml_features_demand_v1 "
    "  WHERE region = $1 "
    "  ORDER BY ts_30 DESC "
    "  LIMIT $2"
    ") recent "
    "ORDER BY ts_30 ASC"
)


async def get_latest_feature_row(
    pool: ConnectionPool, region: str
) -> dict[str, Any] | None:
    """Most recent feature row for `region`, or None if the mart has no data yet."""
    return await pool.fetchrow(_LATEST_FEATURE_ROW_QUERY, region)


async def get_recent_feature_rows(
    pool: ConnectionPool, region: str, lookback: int
) -> list[dict[str, Any]]:
    """The most recent `lookback` rows for `region`, oldest first. May
    return fewer than `lookback` rows if the mart doesn't have that
    much history yet for this region -- callers must check the length.
    """
    return await pool.fetch(_RECENT_FEATURE_ROWS_QUERY, region, lookback)


__all__ = ["get_latest_feature_row", "get_recent_feature_rows"]
