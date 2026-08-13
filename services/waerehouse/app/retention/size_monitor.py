"""Database size monitoring & alerting (README Phase 3 — "tracks total
database size against the 500 MB limit, triggering high-priority alerts
or emergency pruning if storage crosses 80%").

`pg_database_size(current_database())` is the same number Neon's own
dashboard shows for a project's storage usage — this is the real,
authoritative figure, not an estimate derived from row counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import database_size_bytes
from app.db.session import get_session

log = get_logger(__name__)

Severity = Literal["ok", "warning", "emergency"]


@dataclass(frozen=True)
class SizeReport:
    size_bytes: int
    limit_bytes: int
    pct_used: float
    severity: Severity


async def check_database_size() -> SizeReport:
    """Measures the real Postgres database size and classifies it
    against `Settings.database_size_limit_mb`'s `retention_warning_pct`/
    `retention_emergency_pct` thresholds. Pushes the raw byte count to
    `core.metrics.database_size_bytes` as a side effect, so `/metrics`
    always reflects the last time this was checked.
    """
    settings = get_settings()
    limit_bytes = settings.database_size_limit_mb * 1024 * 1024

    async with get_session() as session:
        result = await session.execute(
            text("SELECT pg_database_size(current_database())")
        )
        row = result.first()
        size_bytes = int(row[0]) if row else 0

    database_size_bytes.set(size_bytes)
    pct_used = size_bytes / limit_bytes if limit_bytes else 0.0

    if pct_used >= settings.retention_emergency_pct:
        severity: Severity = "emergency"
    elif pct_used >= settings.retention_warning_pct:
        severity = "warning"
    else:
        severity = "ok"

    report = SizeReport(
        size_bytes=size_bytes,
        limit_bytes=limit_bytes,
        pct_used=pct_used,
        severity=severity,
    )

    log_fn = log.warning if severity != "ok" else log.info
    log_fn(
        "retention.database_size_checked",
        size_bytes=size_bytes,
        limit_bytes=limit_bytes,
        pct_used=round(pct_used, 4),
        severity=severity,
    )
    return report
