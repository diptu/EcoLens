"""Seasonal-naive baseline forecaster.

`forecast-api` never trains -- data-pipeline owns training + MLflow
registration end-to-end (root `TODO.md`'s forecasting section), and no
model is registered yet (`ECO-108`..`ECO-119` are still backlog). This
baseline is the honest v1: a real, working forecast computed straight
from `ml_features_demand_v1`'s precomputed lag columns, not a stub
that returns nulls until the LSTM lands. Once a Production model
exists, it becomes the input to a swapped-in model loader behind the
same `ForecastStep` contract -- no API change.

## The math

`ml_features_demand_v1` gives one row for "now" (`ts_30`) carrying
`demand_mw` (t=0) and `demand_lag_01..demand_lag_48` (t-1..t-48 in
30-min steps, i.e. up to 24h of history). A period-48 seasonal-naive
forecast for `h` steps ahead (h=1..48, i.e. up to 24h out) says
"assume it looks like it did 24h ago, adjusted to be `h` steps past
that same anchor": that value sits `48 - h` steps *before* now, which
is exactly `demand_lag_{48-h}` (and `demand_mw` itself when h=48,
since `48-h=0`).

This is a real forecasting method (persistence/seasonal-naive is a
standard baseline electricity-demand models are benchmarked against),
not a placeholder -- but it is naive: it ignores weather, holidays,
and trend. The P10/P90 band is a simple mean +/- z*std using the
mart's own `demand_rolling_std_7d`, which is *not* conformal
calibration (that requires a held-out calibration split per
`ECO-114`) -- it is a cheap, honestly-labelled approximation so the
response shape matches what real conformal intervals will look like.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

MODEL_NAME = "seasonal_naive_v1"


def _lag_value(row: dict[str, Any], steps_back: int) -> float | None:
    if steps_back == 0:
        return row.get("demand_mw")
    return row.get(f"demand_lag_{steps_back:02d}")


def forecast_from_latest_row(
    row: dict[str, Any],
    *,
    horizon: int,
    interval_minutes: int,
    z_score: float,
) -> list[dict[str, Any]]:
    """Build `horizon` forecast steps from one `ml_features_demand_v1` row.

    `row` must carry `ts_30`, `demand_mw`, `demand_lag_01..demand_lag_48`,
    and `demand_rolling_std_7d`. `horizon` must be <= 48 -- the lag depth
    the mart materializes; asking further out has nothing to anchor on.
    """
    if horizon < 1 or horizon > 48:
        raise ValueError("horizon must be between 1 and 48 (mart's lag depth)")

    base_ts: datetime = row["ts_30"]
    std = row.get("demand_rolling_std_7d") or 0.0

    steps = []
    for h in range(1, horizon + 1):
        point = _lag_value(row, 48 - h)
        p10 = point - z_score * std if point is not None else None
        p90 = point + z_score * std if point is not None else None
        steps.append(
            {
                "ts": base_ts + timedelta(minutes=interval_minutes * h),
                "horizon_step": h,
                "p10": p10,
                "p50": point,
                "p90": p90,
            }
        )
    return steps


__all__ = ["MODEL_NAME", "forecast_from_latest_row"]
