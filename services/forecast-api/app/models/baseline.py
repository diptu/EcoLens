"""Seasonal-naive baseline forecaster (`todo-model-training.md` Phase
0) -- the always-available, nothing-to-load floor every later phase
(multi-model blend, anomaly-triggered fallback) compares against or
falls back to. No training step, no weights: a pure function over
history, real quantiles from real historical values rather than a
fixed +/-X% band.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def seasonal_naive_forecast(
    history: pd.Series,
    horizon: int,
    period_steps: int,
    n_periods: int = 8,
) -> pd.DataFrame:
    """`history`: a `demand_mw`-like series, sorted ascending by
    timestamp, ending at "now" (the forecast origin) -- the last value
    is one step before the first forecasted one. `period_steps`: the
    seasonal period in *rows*, not time (e.g. 2016 for a 5-min series'
    weekly seasonality: 7*24*60/5; 336 for a 30-min series': 7*24*2).
    `n_periods`: how many past occurrences of "the same point in the
    cycle" to pool for the P10/P50/P90 spread -- more periods gives a
    more stable empirical quantile at the cost of needing more history.

    Returns a `horizon`-row DataFrame (`step`, `p10`, `p50`, `p90`),
    `step` = 1..horizon steps ahead of `history`'s last timestamp. P50
    is the pooled sample's *median* (not mean) -- robust to one unusual
    past period skewing the point estimate; P10/P90 are that pool's
    real 10th/90th percentiles, not an arbitrary fixed-width band, so
    they reflect how much this specific point in the cycle actually
    varied historically (e.g. wider around a typical evening peak than
    a quiet overnight trough).
    """
    if period_steps <= 0:
        raise ValueError("period_steps must be positive")
    if n_periods <= 0:
        raise ValueError("n_periods must be positive")

    values = history.to_numpy()
    n = len(values)
    rows: list[dict[str, float]] = []
    for step in range(1, horizon + 1):
        # The step-s forecast target is conceptually at index n+s-1
        # (index n-1 is history's last observed row, step=1 is the next
        # one). One period back from that target, k times, lands on the
        # same phase of the cycle k periods ago.
        target = n + step - 1
        idxs = [target - k * period_steps for k in range(1, n_periods + 1)]
        pool = values[[i for i in idxs if 0 <= i < n]]
        if pool.size == 0:
            rows.append({"step": step, "p10": np.nan, "p50": np.nan, "p90": np.nan})
            continue
        rows.append(
            {
                "step": step,
                "p10": float(np.percentile(pool, 10)),
                "p50": float(np.median(pool)),
                "p90": float(np.percentile(pool, 90)),
            }
        )
    return pd.DataFrame(rows)
