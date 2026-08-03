"""Schemas for `GET/POST /v1/ingestion/*` (API_SPECEFICATIONS.md §2.1-2.8).

See `app.models.pipelines`'s module docstring for why there are 6
pipelines here, not the spec's 8, and `app.service.pipelines`'s for
which fields are real data vs. an honest always-empty/always-null
placeholder for machinery this codebase doesn't have (Prefect, a retry/
backoff scheduler, a DLQ, lineage tracking).
"""

from __future__ import annotations

from app.schemas.pipelines.base import PipelineScheduleInfo, PipelineStatus, Trigger
from app.schemas.pipelines.create import PauseRequest
from app.schemas.pipelines.entities import (
    FailedRunError,
    FailedRunOut,
    PipelineOut,
    PublicRunOut,
    RetryQueueItem,
    RetryQueueLastError,
    RunDetail,
    RunLineage,
    RunOut,
)
from app.schemas.pipelines.response import (
    FailedRunsMeta,
    FailedRunsResponse,
    PauseResponse,
    PipelinesListResponse,
    PipelinesMeta,
    PublicRunsListResponse,
    RecentRunSummary,
    ResumeResponse,
    RetryQueueMeta,
    RetryQueueResponse,
    RunsListResponse,
    RunsMeta,
    SchedulerResponse,
    SchedulerStatus,
    UpcomingRun,
)

__all__ = [
    "FailedRunError",
    "FailedRunOut",
    "FailedRunsMeta",
    "FailedRunsResponse",
    "PauseRequest",
    "PauseResponse",
    "PipelineOut",
    "PipelineScheduleInfo",
    "PipelineStatus",
    "PipelinesListResponse",
    "PipelinesMeta",
    "PublicRunOut",
    "PublicRunsListResponse",
    "RecentRunSummary",
    "ResumeResponse",
    "RetryQueueItem",
    "RetryQueueLastError",
    "RetryQueueMeta",
    "RetryQueueResponse",
    "RunDetail",
    "RunLineage",
    "RunOut",
    "RunsListResponse",
    "RunsMeta",
    "SchedulerResponse",
    "SchedulerStatus",
    "Trigger",
    "UpcomingRun",
]
