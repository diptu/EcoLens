from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel
from app.schemas.datasources import RunStatus
from app.schemas.pipelines.entities import (
    FailedRunOut,
    PipelineOut,
    PublicRunOut,
    RetryQueueItem,
    RunOut,
)

# ── 2.1 GET /v1/ingestion/pipelines ──────────────────────────────────────


class PipelinesMeta(AppBaseModel):
    total: int
    active: int
    paused: int
    as_of: datetime


class PipelinesListResponse(AppBaseModel):
    meta: PipelinesMeta
    data: list[PipelineOut]


# ── 2.2 GET /v1/ingestion/runs, 2.3 GET /v1/ingestion/runs/{id} ─────────


class RunsMeta(AppBaseModel):
    total: int
    filtered: int


class RunsListResponse(AppBaseModel):
    meta: RunsMeta
    data: list[RunOut]
    next_cursor: str | None = None
    has_more: bool


class PublicRunsListResponse(AppBaseModel):
    meta: RunsMeta
    data: list[PublicRunOut]
    next_cursor: str | None = None
    has_more: bool


# ── 2.4 GET /v1/ingestion/failed ─────────────────────────────────────────


class FailedRunsMeta(AppBaseModel):
    total_failed_24h: int
    total_failed_7d: int
    as_of: datetime


class FailedRunsResponse(AppBaseModel):
    meta: FailedRunsMeta
    data: list[FailedRunOut]
    next_cursor: str | None = None
    has_more: bool


# ── 2.5 GET /v1/ingestion/retry-queue ────────────────────────────────────


class RetryQueueMeta(AppBaseModel):
    queue_size: int
    oldest_queued_at: datetime | None = None
    as_of: datetime


class RetryQueueResponse(AppBaseModel):
    meta: RetryQueueMeta
    data: list[RetryQueueItem]


# ── 2.6 GET /v1/ingestion/scheduler ──────────────────────────────────────


class SchedulerStatus(AppBaseModel):
    """`active_workers`/`total_workers` are always `1`/`1` — there's no
    separate worker pool; runs execute in-process (FastAPI
    `BackgroundTasks` for API-triggered runs, the calling GitHub Actions
    runner itself for cron-triggered ones). `prefect_version`/
    `prefect_api_url` are always `None`: the `prefect` container in
    `docker-compose.yml` exists for the (unbuilt) Forecasting pipeline,
    not ingestion — nothing here talks to it."""

    status: Literal["healthy"] = "healthy"
    as_of: datetime
    active_workers: int = 1
    total_workers: int = 1
    queue_depth: int
    prefect_version: str | None = None
    prefect_api_url: str | None = None


class UpcomingRun(AppBaseModel):
    pipeline_id: str
    source_id: str | None = None
    scheduled_at: datetime
    trigger: Literal["schedule"] = "schedule"


class RecentRunSummary(AppBaseModel):
    run_id: str
    pipeline_id: str
    status: RunStatus
    finished_at: datetime | None = None
    duration_ms: int | None = None


class SchedulerResponse(AppBaseModel):
    scheduler: SchedulerStatus
    upcoming_runs: list[UpcomingRun]
    recent_runs: list[RecentRunSummary]


# ── 2.7/2.8 POST /v1/ingestion/{id}/{pause,resume} ───────────────────────


class PauseResponse(AppBaseModel):
    id: str
    status: Literal["paused"] = "paused"
    paused_at: datetime
    paused_by: str
    reason: str | None = None
    in_flight_runs: int
    next_scheduled_run: None = None


class ResumeResponse(AppBaseModel):
    id: str
    status: Literal["active"] = "active"
    resumed_at: datetime
    resumed_by: str
    next_scheduled_run: datetime | None = None
