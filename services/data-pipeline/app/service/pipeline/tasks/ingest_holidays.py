"""Ingest task: AEMO public holidays.

This is a once-a-year pull, not a time-series ingest. The result is a
small (region, date) lookup that dbt joins against `int_demand_with_weather`.
"""

from __future__ import annotations

import uuid
from datetime import date

import pandas as pd

from app.db.redis import get_breaker
from app.core.logging import get_logger
from app.service.pipeline.tasks._common import timed

log = get_logger(__name__)

REGIONS: tuple[str, ...] = ("NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM")

# NSW national public holidays; other states add their own regional ones.
# This is the minimum set; AEMO publishes the full list annually.
_BASE_HOLIDAYS: tuple[tuple[str, str], ...] = (
    ("New Year's Day", "01-01"),
    ("Australia Day", "01-26"),
    ("Good Friday", "varies"),  # would be computed from Easter
    ("Easter Monday", "varies"),
    ("Anzac Day", "04-25"),
    ("Christmas Day", "12-25"),
    ("Boxing Day", "12-26"),
)


@timed("aemo_holidays")
async def run(year: int | None = None) -> pd.DataFrame:
    # Resolved here, not inside `_do_fetch` — assigning to `year` in that
    # nested function would make Python treat it as a new local variable
    # for the *entire* function body, so the `year is None` check would
    # read it before assignment and raise UnboundLocalError.
    resolved_year = year if year is not None else date.today().year
    breaker = get_breaker("aemo_holidays")

    async def _do_fetch() -> pd.DataFrame:
        # In production: download AEMO's published holiday list per region.
        # In dev: derive from the static `_BASE_HOLIDAYS` table.
        return _build_for_year(resolved_year)

    return await breaker.call(_do_fetch)


def _build_for_year(year: int) -> pd.DataFrame:
    """Build the holiday df for one year, across all regions."""
    rows: list[dict] = []
    for region in REGIONS:
        for name, md in _BASE_HOLIDAYS:
            if md == "varies":
                continue  # easter dates need a calendar lib; skip in stub
            month_str, day_str = md.split("-")
            rows.append(
                {
                    "date": pd.Timestamp(
                        year=year, month=int(month_str), day=int(day_str)
                    ).date(),
                    "region": region,
                    "holiday_name": name,
                    "is_workday": False,
                    "source": "aemo_holidays",
                    "ingested_at": pd.Timestamp.now(tz="UTC"),
                    "ingest_run_id": str(uuid.uuid4()),
                }
            )
    df = pd.DataFrame(rows)
    log.info("aemo_holidays.built", year=year, rows=len(df))
    return df
