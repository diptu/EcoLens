from __future__ import annotations

from app.schemas.base import AppBaseModel

_ALL_TEST_CATEGORIES = (
    "completeness",
    "validity",
    "uniqueness",
    "consistency",
    "timeliness",
)


class RecheckRequest(AppBaseModel):
    tests: list[str] = list(_ALL_TEST_CATEGORIES)
    window: str = "P1D"
