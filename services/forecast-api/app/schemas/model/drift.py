"""`GET /v1/model/drift` -- real per-feature PSI/KS drift report,
backing the dashboard's Performance page "Concept drift tracking" card.
See `app/service/mlops/live_drift.py`'s own docstring for what
"reference"/"comparison" mean here and their real, disclosed
limitation."""

from __future__ import annotations

from app.schemas.base import AppBaseModel


class DriftReportOut(AppBaseModel):
    feature: str
    # `None`, not NaN -- `drift.py`'s PSI/KS can come back NaN (e.g. a
    # reference slice with zero real spread to bin against), and NaN
    # isn't valid JSON; `None` is the honest "not computable" value a
    # JSON client can actually parse.
    psi: float | None
    psi_severity: str
    ks_statistic: float | None
    ks_pvalue: float | None
    reference_n: int
    comparison_n: int


class DriftListResponse(AppBaseModel):
    data: list[DriftReportOut]
