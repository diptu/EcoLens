from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.models.pipelines import Stage
from app.schemas.base import AppBaseModel
from app.schemas.datasources import RunStatus
from app.schemas.pipelines.base import PipelineScheduleInfo, PipelineStatus


# ── 2.1 GET /v1/ingestion/pipelines ──────────────────────────────────────


class PipelineOut(AppBaseModel):
    id: str
    name: str
    source_id: str | None = None
    stage: Stage
    status: PipelineStatus
    schedule: PipelineScheduleInfo
    depends_on: list[str] = []
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    run_count_24h: int
    success_rate_24h: float | None = None
    p95_duration_ms_24h: int | None = None


# ── 2.2 GET /v1/ingestion/runs, 2.3 GET /v1/ingestion/runs/{id} ─────────


class RunOut(AppBaseModel):
    id: str
    pipeline_id: str
    source_id: str
    status: RunStatus
    trigger: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    records_fetched: int | None = None
    records_inserted: int | None = None
    duplicates_skipped: int | None = None
    anomalies_flagged: int | None = None
    error: str | None = None
    metadata: dict[str, object] = {}


class PublicRunOut(AppBaseModel):
    """`RunOut` minus `error` (raw `str(exception)[:500]` -- not needed
    for the dashboard's Runs tab, and not worth the redaction risk
    `PublicFailedRunOut`-equivalent fields already carry, see
    `service.pipelines`'s `list_failed_public`) and `metadata` (its
    `hostname` key is internal infra detail, not something to expose
    unauthenticated). Backs `GET /v1/ingestion/public/runs`."""

    id: str
    pipeline_id: str
    source_id: str
    status: RunStatus
    trigger: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    records_fetched: int | None = None
    records_inserted: int | None = None
    duplicates_skipped: int | None = None
    anomalies_flagged: int | None = None


class RunLineage(AppBaseModel):
    """Always `input_datasets=[]`/`downstream_runs=[]` — this service
    doesn't track cross-run lineage (no automatic ingest -> dbt dependency
    chain; `pipe-dbt-warehouse` is manual-trigger-only, see
    `pipelines.catalog`'s docstring). `output_datasets` is real: the
    `raw.*` table `registry.SOURCES[key].table` says this run's source
    writes to."""

    input_datasets: list[str] = []
    output_datasets: list[str] = []
    downstream_runs: list[str] = []


class RunDetail(RunOut):
    lineage: RunLineage
    retry_chain: list[str] = []
    logs_url: str | None = None
    prefect_ui_url: str | None = None


# ── 2.4 GET /v1/ingestion/failed ─────────────────────────────────────────


class FailedRunError(AppBaseModel):
    code: str | None = None
    message: str
    http_status: int | None = None
    retryable: bool


class FailedRunOut(AppBaseModel):
    run_id: str
    pipeline_id: str
    source_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error: FailedRunError
    retry_count: int = 0
    next_retry_at: datetime | None = None
    in_dlq: bool = False
    can_retry_now: bool


# ── 2.5 GET /v1/ingestion/retry-queue ────────────────────────────────────


class RetryQueueLastError(AppBaseModel):
    code: str | None = None
    message: str


class RetryQueueItem(AppBaseModel):
    """Backed by `meta._ingest_log` rows with `status='sync_failed'` —
    fetched fine, but the warehouse-sync consumer failed to load them into
    Postgres (the staged DuckDB file is deliberately left on disk as the
    recovery artifact, `pipeline.warehouse_sync`'s docstring). There is no
    automated backoff/retry scheduler anywhere in this codebase — a
    `sync_failed` run just sits here until an operator intervenes (re-run
    `warehouse-sync`, or re-trigger the source and let `ON CONFLICT DO
    NOTHING` dedup the eventual double-load). `next_retry_at`/
    `retry_count`/`max_retries` are honestly null/0/null rather than
    fabricating an exponential-backoff engine that doesn't exist;
    `backoff_strategy` is always `"manual"`."""

    queue_id: str
    run_id: str
    pipeline_id: str
    source_id: str
    queued_at: datetime
    next_retry_at: datetime | None = None
    retry_count: int = 0
    max_retries: int | None = None
    last_error: RetryQueueLastError
    backoff_strategy: Literal["manual"] = "manual"
    backoff_base_seconds: int | None = None
