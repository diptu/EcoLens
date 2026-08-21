"""Response schemas for `GET /v1/data-quality/summary/public` -- ported
from data-pipeline's `app/schemas/data_quality/response.py`, the summary
section only (`DataQualitySummaryResponse`/`PublicDataQualitySummaryResponse`
and their two nested types). The `issues`/`outliers`/`schema` sections of
that module back routes nothing in this platform currently calls (the
dashboard's `lib/data-quality.ts` only ever wires up the public summary
-- see that file's own docstring), so they aren't ported here; add them
if/when something actually consumes them, rather than carrying dead
schema surface forward speculatively.
"""

from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel


class OverallSummary(AppBaseModel):
    pass_rate_pct_24h: float | None = None
    pass_rate_pct_7d: float | None = None
    total_tests_24h: int
    tests_passed_24h: int
    tests_failed_24h: int
    tests_warned_24h: int


class BySourceSummary(AppBaseModel):
    source_id: str
    pass_rate_pct: float | None = None
    issues: int


class DataQualitySummaryResponse(AppBaseModel):
    as_of: datetime
    overall: OverallSummary
    by_severity_24h: dict[str, int]
    by_source_24h: list[BySourceSummary]
    by_category_24h: dict[str, int]


class PublicDataQualitySummaryResponse(AppBaseModel):
    """Backs `GET /v1/data-quality/summary/public` -- an unauthenticated
    projection of `DataQualitySummaryResponse` exposing only two
    aggregate numbers safe to hand to a browser client with no bearer
    token: no source IDs, descriptions, or per-issue detail, just
    overall counts. ecoLens dashboard's Executive Dashboard uses this to
    back its "Data Quality Score"/"Open Risks" KPIs."""

    as_of: datetime
    data_quality_score_pct: float | None = None
    open_risks_high_plus: int


class OpenRiskOut(AppBaseModel):
    """One real `high`/`critical`-severity open issue -- the actual
    per-issue detail `PublicDataQualitySummaryResponse.open_risks_high_plus`
    counts but never names (2026-08-20 -- the Executive Dashboard's "Open
    Risks" KPI showed a bare count with no way to see which service or
    why; this is what backs the fix). Same three real sources
    `_generate_issues` already produces -- consecutive ingest-run
    failures, anomaly clusters, and actionable schema drift -- just
    surfaced instead of only counted."""

    id: str
    source_id: str
    source_name: str
    severity: str
    category: str
    title: str
    description: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int
    suggested_action: str


class OpenRisksListResponse(AppBaseModel):
    as_of: datetime
    data: list[OpenRiskOut]
