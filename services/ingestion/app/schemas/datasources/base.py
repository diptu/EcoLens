"""Shared literal types + component schemas for the data-source catalog.

Now the full set, matching data-pipeline's identical module — the
admin-gated list/get/patch/health/history endpoints these back were
originally deferred ("Expose CLI & API Routers", trigger-only for now,
pending a real cross-service auth story) but are now ported too, using
`app.core.security`'s verification-only JWT bearer auth (see that
module's own docstring for how this service verifies tokens without
issuing its own).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel

Category = Literal["grid", "weather", "carbon", "fuel", "custom"]
HealthStatus = Literal["healthy", "degraded", "failing", "paused"]
CircuitBreakerState = Literal["closed", "open", "half_open"]
# "staged"/"sync_failed" are ecoLens-specific additions beyond the spec's
# original success/failed/running/queued vocabulary — see docs/data/
# ingestion.md: a run is "staged" once fetched and handed to RabbitMQ,
# and only "success" once whichever service still runs `pipeline.
# warehouse_sync` actually lands it in Postgres.
RunStatus = Literal[
    "success", "failed", "running", "staged", "sync_failed", "queued", "partial"
]
AuthType = Literal["none", "api_key", "oauth2"]


class AuthInfo(AppBaseModel):
    type: AuthType


class ScheduleInfo(AppBaseModel):
    cron: str
    cadence: str
    timezone: str
    enabled: bool
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None


class HealthInfo(AppBaseModel):
    status: HealthStatus
    success_rate_pct_24h: float | None = None
    success_rate_pct_7d: float | None = None
    p50_duration_ms: int | None = None
    p95_duration_ms: int | None = None
    p99_duration_ms: int | None = None
    consecutive_failures: int
    circuit_breaker: CircuitBreakerState
    last_check_at: datetime


class LastRunInfo(AppBaseModel):
    id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    records_fetched: int | None = None
    records_inserted: int | None = None
    duplicates_skipped: int | None = None
    anomalies_flagged: int | None = None
    error: str | None = None
