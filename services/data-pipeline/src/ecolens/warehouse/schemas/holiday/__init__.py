"""`HolidayRow`/`PaginatedHolidays` — public holiday metadata
(`dim_holiday`), paginated for `/holidays/{year}`.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class HolidayRow(BaseModel):
    date: date
    region: str
    state: str
    holiday_name: str
    holiday_type: str
    is_observed: bool = False
    days_until: int | None = None


class PaginatedHolidays(BaseModel):
    items: list[HolidayRow]
    total: int
    limit: int
    offset: int


__all__ = ["HolidayRow", "PaginatedHolidays"]
