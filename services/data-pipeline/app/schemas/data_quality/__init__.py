"""Schemas for `GET /v1/data-quality/{summary,issues,outliers,schema}` and
`POST /v1/data-quality/recheck/{source}` (API_SPECEFICATIONS.md §3.1-3.5).

"Data quality tests" in the spec's own vocabulary map onto real signals
this service already produces rather than a fabricated dbt-test-results
tracker (there is no such tracker — dbt tests aren't parsed/persisted
anywhere): each ingest run counts as one test (pass/fail/warn), and
`meta.anomalies`/`meta.schema_drifts` supply the issue/outlier/drift
detail. See `app.service.dataquality`'s module docstring for the
exact mapping.
"""

from __future__ import annotations

from app.schemas.data_quality.base import (
    DriftKind,
    IssueCategory,
    IssueStatus,
    Severity,
)
from app.schemas.data_quality.create import RecheckRequest
from app.schemas.data_quality.entities import (
    DataQualityIssue,
    DataQualityOutlier,
    ExpectedRange,
    OutlierContext,
    SchemaDriftOut,
)
from app.schemas.data_quality.response import (
    BySourceSummary,
    DataQualityIssuesMeta,
    DataQualityIssuesResponse,
    DataQualityOutliersMeta,
    DataQualityOutliersResponse,
    DataQualitySchemaResponse,
    DataQualitySummaryResponse,
    OverallSummary,
    PublicDataQualitySummaryResponse,
    RecheckResponse,
    SchemaDriftSummary,
)

__all__ = [
    "BySourceSummary",
    "DataQualityIssue",
    "DataQualityIssuesMeta",
    "DataQualityIssuesResponse",
    "DataQualityOutlier",
    "DataQualityOutliersMeta",
    "DataQualityOutliersResponse",
    "DataQualitySchemaResponse",
    "DataQualitySummaryResponse",
    "DriftKind",
    "ExpectedRange",
    "IssueCategory",
    "IssueStatus",
    "OutlierContext",
    "OverallSummary",
    "PublicDataQualitySummaryResponse",
    "RecheckRequest",
    "RecheckResponse",
    "SchemaDriftOut",
    "SchemaDriftSummary",
    "Severity",
]
