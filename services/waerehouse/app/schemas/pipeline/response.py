from __future__ import annotations

from app.schemas.base import AppBaseModel


class StorageUtilization(AppBaseModel):
    """`GET /v1/pipeline/storage` -- the real, authoritative
    `pg_database_size` figure (`retention.size_monitor`), not an
    estimate."""

    size_bytes: int
    limit_bytes: int
    pct_used: float
    severity: str


class SyncActivity(AppBaseModel):
    """`GET /v1/pipeline/status` -- `meta._ingest_log` status counts over
    the lookback window (README Phase 5's "downstream services... query
    pipeline health"). `staged` rows this old are a real signal
    something's stuck -- the consumer should have closed them out to
    `success`/`sync_failed` well within the window."""

    window_hours: int
    success: int
    sync_failed: int
    staged: int
