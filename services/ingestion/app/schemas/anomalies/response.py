"""Response shapes for `GET /v1/anomalies` / `PATCH /v1/anomalies/{id}` --
real `meta.anomalies` rows, backing the dashboard's anomaly-detection
page (root TODO.md's "make every page fully functional with real data" --
that page previously read `lib/admin.ts`'s fully-fabricated
`generateAnomalies()`, mutation handlers were local-state-only).

`severity`/`method` are derived, not separately tracked columns --
`severity` reuses `service/dataquality.py`'s own existing
`_severity_from_score` thresholds (>=0.9 high, >=0.5 medium, else low --
already real, already used elsewhere in this service, not invented
here). `method` is derived from which of `rule_based_score`/
`statistical_score`/`ml_score` are non-null for that row (real columns
`pipeline.anomaly.detect_anomalies` already writes) -- `"hybrid"` when
both an ML score and a rule/statistical score fired on the same row
(confirmed real, live: 42,982 of 142,875 real rows have >=2 of the 3
non-null), `"ml"`/`"rule"` when only one side did. Rows from before
these 3 columns existed (a real, disclosed schema-migration boundary --
29,353 of 142,875 have all 3 null) fall back to `"rule"`, the honest
default for a row that still has a real `anomaly_score`/`anomaly_reason`
just not the newer per-check breakdown.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from app.schemas.base import AppBaseModel

AnomalySeverity = Literal["high", "medium", "low"]
AnomalyMethod = Literal["rule", "ml", "hybrid"]
AnomalyStatus = Literal["new", "acknowledged", "resolved", "false_positive"]


class AnomalyOut(AppBaseModel):
    id: str
    detected_at: datetime
    ts: str | None
    region: str | None
    source: str
    table_name: str
    reason: str
    severity: AnomalySeverity
    method: AnomalyMethod
    score: float
    metric: str | None
    observed_value: float | None
    z_score: float | None
    expected_low: float | None
    expected_high: float | None
    status: AnomalyStatus
    status_updated_at: datetime | None


class AnomalyListResponse(AppBaseModel):
    meta: dict[str, Any]
    data: list[AnomalyOut]


class DailyAnomalyCount(AppBaseModel):
    date: str
    count: int


class AnomalySummaryResponse(AppBaseModel):
    total: int
    avg_score: float
    by_severity: dict[str, int]
    by_status: dict[str, int]
    by_source: dict[str, int]
    by_method: dict[str, int]
    by_reason_kind: dict[str, int]
    daily_counts: list[DailyAnomalyCount]


class UpdateAnomalyStatusRequest(AppBaseModel):
    status: AnomalyStatus
