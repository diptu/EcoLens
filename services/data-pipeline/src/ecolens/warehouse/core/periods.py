"""Period-window resolution for `/api/analytics/executive-kpis`.

Each supported `period` value resolves to a *current* window and a
*previous* window of the same elapsed duration, one year (ytd/qtd) or
one window-length (30d/7d) earlier — what `delta_pct` on every KPI
card compares against. Same elapsed-duration rule for every period so
`delta_pct` is always a like-for-like comparison, not e.g. 5 months of
this year against all 12 months of last year (the naive read of the
endpoint spec's own example response, which shows `meta.previous_period`
as the *full* prior calendar year for a `ytd` request that's only
~5 months elapsed — arithmetically inconsistent with the `delta_pct`/
`sub` values in that same example, which only reconcile against a
like-for-like prior-YTD window; treated as a documentation artifact in
the source spec, not a deliberate design, so not reproduced here).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

VALID_PERIODS: tuple[str, ...] = ("ytd", "qtd", "30d", "7d")

PERIOD_LABELS: dict[str, str] = {
    "ytd": "YTD",
    "qtd": "QTD",
    "30d": "Last 30 Days",
    "7d": "Last 7 Days",
}


@dataclass(frozen=True)
class PeriodWindow:
    period: str
    current_since: datetime
    current_until: datetime
    previous_since: datetime
    previous_until: datetime


def _quarter_start_month(month: int) -> int:
    return 3 * ((month - 1) // 3) + 1


def resolve_period(period: str, now: datetime | None = None) -> PeriodWindow:
    """Raises `ValueError` for an unknown `period` — callers validate
    against `VALID_PERIODS` before this (see `api/read_dependencies.py`),
    so this is a defensive check, not the primary 400 path.
    """
    if period not in VALID_PERIODS:
        raise ValueError(f"unknown period {period!r}; valid: {VALID_PERIODS}")

    now = now or datetime.now(timezone.utc)

    if period == "ytd":
        current_since = datetime(now.year, 1, 1, tzinfo=timezone.utc)
        current_until = now
        elapsed = current_until - current_since
        previous_since = datetime(now.year - 1, 1, 1, tzinfo=timezone.utc)
        previous_until = previous_since + elapsed
    elif period == "qtd":
        q_month = _quarter_start_month(now.month)
        current_since = datetime(now.year, q_month, 1, tzinfo=timezone.utc)
        current_until = now
        elapsed = current_until - current_since
        previous_since = datetime(now.year - 1, q_month, 1, tzinfo=timezone.utc)
        previous_until = previous_since + elapsed
    elif period == "30d":
        current_until = now
        current_since = now - timedelta(days=30)
        previous_until = current_since
        previous_since = current_since - timedelta(days=30)
    else:  # "7d"
        current_until = now
        current_since = now - timedelta(days=7)
        previous_until = current_since
        previous_since = current_since - timedelta(days=7)

    return PeriodWindow(
        period=period,
        current_since=current_since,
        current_until=current_until,
        previous_since=previous_since,
        previous_until=previous_until,
    )


__all__ = ["VALID_PERIODS", "PERIOD_LABELS", "PeriodWindow", "resolve_period"]
