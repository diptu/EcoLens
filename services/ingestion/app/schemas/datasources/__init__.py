"""Schemas for the full `/v1/data-sources` surface this service exposes:
trigger-only (`POST .../run`, `POST .../backfill`, `GET .../backfill/
status`, no auth) plus the admin-gated list/detail/patch/health/history
endpoints (`app.core.security`'s verification-only JWT bearer auth)."""

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
