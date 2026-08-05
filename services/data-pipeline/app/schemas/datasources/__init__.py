"""Schemas for `GET /v1/data-sources[/{id}]`, `PATCH /v1/data-sources/{id}`,
`POST /v1/data-sources/{id}/run`, `POST /v1/data-sources/{id}/backfill`,
`GET /v1/data-sources/{id}/health`, `GET /v1/data-sources/{id}/history`
(API_SPECEFICATIONS.md §1.1-1.6)."""

from __future__ import annotations

from app.schemas.datasources.base import (
    AuthInfo,
    AuthType,
    Category,
    CircuitBreakerState,
    HealthInfo,
    HealthStatus,
    LastRunInfo,
    RunStatus,
    ScheduleInfo,
)
from app.schemas.datasources.create import (
    AuthUpdate,
    BackfillRequest,
    PatchDataSourceRequest,
    RunRequest,
    ScheduleUpdate,
)
from app.schemas.datasources.entities import DataSourceOut
from app.schemas.datasources.response import (
    BackfillStatusResponse,
    BackfillTriggerResponse,
    CircuitBreakerDetail,
    DataSourcesListResponse,
    DataSourcesMeta,
    HistoryRun,
    RecentRun,
    RunTriggerResponse,
    SourceHealthResponse,
    SourceHistoryResponse,
)

__all__ = [
    "AuthInfo",
    "AuthType",
    "AuthUpdate",
    "BackfillRequest",
    "BackfillStatusResponse",
    "BackfillTriggerResponse",
    "Category",
    "CircuitBreakerDetail",
    "CircuitBreakerState",
    "DataSourceOut",
    "DataSourcesListResponse",
    "DataSourcesMeta",
    "HealthInfo",
    "HealthStatus",
    "HistoryRun",
    "LastRunInfo",
    "PatchDataSourceRequest",
    "RecentRun",
    "RunRequest",
    "RunStatus",
    "RunTriggerResponse",
    "ScheduleInfo",
    "ScheduleUpdate",
    "SourceHealthResponse",
    "SourceHistoryResponse",
]
