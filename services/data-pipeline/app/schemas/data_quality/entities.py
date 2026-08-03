from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel
from app.schemas.data_quality.base import (
    DriftKind,
    IssueCategory,
    IssueStatus,
    Severity,
)


class DataQualityIssue(AppBaseModel):
    id: str
    source_id: str
    pipeline_id: str
    severity: Severity
    category: IssueCategory
    title: str
    description: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int
    status: IssueStatus
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    suggested_action: str | None = None
    auto_resolvable: bool


class ExpectedRange(AppBaseModel):
    low: float | None = None
    high: float | None = None


class OutlierContext(AppBaseModel):
    rolling_median_24h: float | None = None
    rolling_std_24h: float | None = None


class DataQualityOutlier(AppBaseModel):
    id: str
    source_id: str
    metric: str
    value: float
    expected_range: ExpectedRange
    z_score: float
    observed_at: datetime
    region: str | None = None
    station_id: str | None = None
    context: OutlierContext | None = None
    linked_issue_id: str | None = None


class SchemaDriftOut(AppBaseModel):
    source_id: str
    table: str
    severity: Severity
    kind: DriftKind
    column: str
    old_type: str | None = None
    new_type: str | None = None
    first_seen_at: datetime
    auto_adapted: bool
    action_required: bool
    downstream_impact: str | None = None
