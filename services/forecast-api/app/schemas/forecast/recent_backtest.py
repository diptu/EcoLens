from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class RecentBacktestPointOut(AppBaseModel):
    ts: datetime
    #: `None` for a real timestamp the warehouse hasn't landed actual
    #: demand for yet (a genuine gap, not an error) -- the predicted
    #: fields are still real for that step (see `evaluate_recent_actual_
    #: vs_predicted`'s own docstring for why a partial gap doesn't drop
    #: the whole step).
    actual: float | None
    p10: float
    p50: float
    p90: float
    #: Real 1-indexed hours-ahead-of-its-own-origin (the horizon step of
    #: the real walk-forward window this point came from) -- see
    #: `evaluate.py`'s `RecentBacktestPoint` for the full reasoning.
    step_hours: int
    unit: Literal["MW"] = "MW"


class RecentBacktestResponse(AppBaseModel):
    """`GET /v1/forecast/recent-actual-vs-predicted` — a real walk-forward
    re-forecast of the model's own served version against real actual
    demand for roughly the last `days_requested` days, ending at the
    most recent real origin the warehouse actually has (see `service/ml/
    evaluate.py`'s `evaluate_recent_actual_vs_predicted` for the full
    real-data/real-gap reasoning). Not a live forecast (`ForecastResponse`
    already covers that) -- this is retrospective, built on demand from
    real history each request, since nothing in this platform persists
    a rolling history of past predictions to read back later."""

    region: str
    model: str
    generated_at: datetime
    horizon_hours: int
    interval: str
    days_requested: int
    points: list[RecentBacktestPointOut]
