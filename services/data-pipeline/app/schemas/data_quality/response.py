from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel
from app.schemas.data_quality.entities import (
    DataQualityIssue,
    DataQualityOutlier,
    SchemaDriftOut,
)


# ── §3.1 GET /v1/data-quality/summary ────────────────────────────────────


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
    overall counts. Ecolens dashboard's Executive Dashboard uses this to
    back its "Data Quality Score" and "Open Risks" KPIs -- see that
    page's docs for why those replaced the platform's old fabricated
    "Compliance Score"/"Open Risks" mock (no sustainability-regulatory
    compliance or risk-register domain exists anywhere in this repo;
    this real ingestion/data-quality signal is the closest honest
    substitute)."""

    as_of: datetime
    data_quality_score_pct: float | None = None
    open_risks_high_plus: int


# ── §3.2 GET /v1/data-quality/issues ─────────────────────────────────────


class DataQualityIssuesMeta(AppBaseModel):
    total: int
    filtered: int


class DataQualityIssuesResponse(AppBaseModel):
    meta: DataQualityIssuesMeta
    data: list[DataQualityIssue]
    next_cursor: str | None = None
    has_more: bool


# ── §3.3 GET /v1/data-quality/outliers ───────────────────────────────────


class DataQualityOutliersMeta(AppBaseModel):
    total: int
    as_of: datetime


class DataQualityOutliersResponse(AppBaseModel):
    meta: DataQualityOutliersMeta
    data: list[DataQualityOutlier]


# ── §3.4 GET /v1/data-quality/schema ─────────────────────────────────────


class SchemaDriftSummary(AppBaseModel):
    total_drifts_24h: int
    auto_adapted: int
    needs_action: int


class DataQualitySchemaResponse(AppBaseModel):
    as_of: datetime
    drifts: list[SchemaDriftOut]
    summary: SchemaDriftSummary


# ── §3.5 POST /v1/data-quality/recheck/{source} ──────────────────────────


class RecheckResponse(AppBaseModel):
    """`window` drives a real re-fetch, not a no-op — `dataquality.
    service.trigger_recheck` converts it to `lookback_minutes` and
    triggers the same background re-run `POST /v1/data-sources/{id}/run`
    uses, so a recheck actually re-validates fresh data (anomaly
    detection re-runs on the new fetch) plus a fresh schema-drift scan —
    not a re-read of already-computed results."""

    recheck_id: str
    source_id: str
    status: Literal["queued"] = "queued"
    tests: list[str]
    window: str
    estimated_completion_at: datetime
    result_url: str
