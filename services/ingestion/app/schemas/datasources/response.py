"""Response bodies for the data-source endpoints this service exposes —
see `base.py`'s module docstring for the trigger-only-then-full history."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel
from app.schemas.datasources.base import CircuitBreakerState, HealthStatus, RunStatus
from app.schemas.datasources.entities import DataSourceOut


class RunTriggerResponse(AppBaseModel):
    """202 — the fetch is handed off to `registry.run_source` via
    `BackgroundTasks`, not awaited before responding. `run_id` here is a
    synthetic trigger id (`run-{epoch}-{5 hex chars}`) — it is *not*
    `meta._ingest_log.id`, since that UUID doesn't exist yet at response
    time.
    """

    run_id: str
    source_id: str
    status: Literal["queued"] = "queued"
    queued_at: datetime
    estimated_start_at: datetime
    priority: Literal["low", "normal", "high"] = "high"
    triggered_by: str
    reason: str | None = None
    deduplicate: bool
    force: bool


class BackfillTriggerResponse(AppBaseModel):
    """202 — same synthetic-id/background-task caveat as
    `RunTriggerResponse`. `chunk` is accepted and reported back but
    execution is always day-granularity under the hood
    (`pipeline.backfill.backfill`, which is what this delegates to) —
    `PT1H`/`P1W` change `total_chunks`'/`estimated_duration_seconds`'
    arithmetic, not the actual fetch granularity.
    """

    backfill_id: str
    source_id: str
    status: Literal["queued"] = "queued"
    queued_at: datetime
    start: datetime
    end: datetime
    chunk: str
    concurrency: int
    deduplicate: bool
    total_chunks: int
    estimated_duration_seconds: int
    triggered_by: str
    progress_url: str


class BackfillStatusResponse(AppBaseModel):
    """`GET /v1/data-sources/{id}/backfill/status` — surfaces the same
    `backfill:lock:{id}` Redis key `trigger_backfill`'s 409 check reads
    (`actions._backfill_in_progress`), so a client can rehydrate "a
    backfill is running" after a page refresh. `trigger` echoes the
    original `BackfillTriggerResponse` so a client that missed it can
    resume progress polling with the same `queued_at`/`total_chunks`.
    """

    source_id: str
    running: bool
    trigger: BackfillTriggerResponse | None = None


# ── list/detail ───────────────────────────────────────────────────────


class DataSourcesMeta(AppBaseModel):
    total: int
    enabled_count: int
    disabled_count: int
    healthy_count: int
    degraded_count: int
    failing_count: int
    paused_count: int
    as_of: datetime
    next_refresh_at: datetime


class DataSourcesListResponse(AppBaseModel):
    meta: DataSourcesMeta
    data: list[DataSourceOut]
    next_cursor: str | None = None
    has_more: bool


# ── health ────────────────────────────────────────────────────────────


class CircuitBreakerDetail(AppBaseModel):
    state: CircuitBreakerState
    opened_at: datetime | None = None
    half_open_at: datetime | None = None
    recovery_seconds: int


class RecentRun(AppBaseModel):
    id: str
    status: RunStatus
    duration_ms: int | None = None
    records: int | None = None
    at: datetime


class SourceHealthResponse(AppBaseModel):
    source_id: str
    status: HealthStatus
    as_of: datetime
    success_rate_pct_1h: float | None = None
    success_rate_pct_24h: float | None = None
    success_rate_pct_7d: float | None = None
    success_rate_pct_30d: float | None = None
    p50_duration_ms: int | None = None
    p95_duration_ms: int | None = None
    p99_duration_ms: int | None = None
    consecutive_failures: int
    circuit_breaker: CircuitBreakerDetail
    last_5_runs: list[RecentRun]
    errors_by_code_24h: dict[str, int]


# ── history ───────────────────────────────────────────────────────────


class HistoryRun(AppBaseModel):
    id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    records_fetched: int | None = None
    records_inserted: int | None = None
    duplicates_skipped: int | None = None
    anomalies_flagged: int | None = None
    trigger: str
    error: str | None = None


class SourceHistoryResponse(AppBaseModel):
    source_id: str
    total: int
    data: list[HistoryRun]
    next_cursor: str | None = None
    has_more: bool
