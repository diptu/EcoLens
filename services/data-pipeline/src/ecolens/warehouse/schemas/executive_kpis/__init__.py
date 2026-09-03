"""`/api/analytics/executive-kpis` response shapes.

Field names/shape follow that endpoint's spec exactly (`id`, `label`,
`value`, `value_display`, `unit`, `delta_pct`, `trend`, `good_when`,
`is_good`, `sub`, `sparkline`) so the Next.js BFF/dashboard can
consume this without any field-renaming glue.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Trend = Literal["up", "down", "flat"]


class KpiCard(BaseModel):
    id: str
    label: str
    value: float | None = None
    value_display: str
    unit: str
    delta_pct: float | None = None
    trend: Trend
    good_when: Trend
    is_good: bool
    sub: str | None = None
    sparkline: list[float] = []


class PreviousPeriod(BaseModel):
    start: datetime
    end: datetime


class ExecutiveKpisMeta(BaseModel):
    period: str
    region: str
    currency: str
    as_of: datetime
    previous_period: PreviousPeriod
    generated_at: datetime


class ExecutiveKpisResponse(BaseModel):
    meta: ExecutiveKpisMeta
    kpis: list[KpiCard]


__all__ = [
    "Trend",
    "KpiCard",
    "PreviousPeriod",
    "ExecutiveKpisMeta",
    "ExecutiveKpisResponse",
]
