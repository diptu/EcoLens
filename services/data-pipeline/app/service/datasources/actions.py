"""`POST /v1/data-sources/{id}/run` and `POST /v1/data-sources/{id}/backfill`
(API_SPECEFICATIONS.md §1.3-1.4).

Both endpoints return `202 Queued` immediately (their own latency budgets
— "< 200 ms" / "< 200 ms" — aren't compatible with waiting for a real
upstream fetch) and hand the actual work off to a FastAPI
`BackgroundTasks` callback. There's no separate task queue/worker in this
service beyond that — see `RunTriggerResponse`/`BackfillTriggerResponse`'s
docstrings in `api/schemas/datasources.py` for what that does and doesn't
give you (no durable queue, no retry-on-crash; a process restart between
"202 returned" and "background task finishes" loses the in-flight run,
same as it would for any other in-process background task).
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.schemas.datasources import (
    BackfillRequest,
    BackfillTriggerResponse,
    RunRequest,
    RunTriggerResponse,
)
from app.db.redis import get_breaker
from app.service.datasources.service import require_catalog_entry
from app.core.logging import get_logger
from app.service.pipeline.backfill import backfill as run_backfill
from app.service.pipeline.circuit_breaker import CircuitState
from app.service.pipeline.tasks.registry import run_source

log = get_logger(__name__)

IDEMPOTENCY_TTL_SECONDS = 3600
_BACKFILL_MAX_DAYS = 90
# API_SPECEFICATIONS.md §1.4 only documents these 3 chunk values; execution
# is always day-granularity regardless (see BackfillTriggerResponse's
# docstring) so a generic ISO-8601-duration parser would be more general
# than what's actually needed.
_CHUNK_SECONDS = {"PT1H": 3600, "P1D": 86400, "P1W": 604800}


def _synthetic_run_id(prefix: str) -> str:
    return f"{prefix}-{int(datetime.now(UTC).timestamp())}-{uuid.uuid4().hex[:5]}"


async def _already_in_flight(db: AsyncSession, source: str) -> bool:
    """`meta._ingest_log` has a `running`/`staged` row for `source` —
    used for `POST .../run`'s 409 `already_running`. Deliberately no time
    bound: a permanently-stuck `staged` row (the warehouse-sync consumer
    crashed) needs an operator to notice and intervene, same philosophy
    as the rest of this codebase's recovery playbook
    (`pipeline/tasks/task.md`) — silently ignoring it after some timeout
    would let a duplicate run start against data that's still mid-sync.
    """
    result = await db.execute(
        text(
            "SELECT 1 FROM meta._ingest_log "
            "WHERE source = :source AND status IN ('running', 'staged') LIMIT 1"
        ),
        {"source": source},
    )
    return result.first() is not None


async def trigger_run(
    db: AsyncSession,
    redis: Redis,
    id: str,
    body: RunRequest,
    *,
    idempotency_key: str | None,
    reason: str | None,
    triggered_by: str,
) -> RunTriggerResponse:
    entry = require_catalog_entry(id)
    source = entry.ingest_source

    idem_cache_key = None
    if idempotency_key:
        idem_cache_key = f"idempotency:datasources:{id}:run:{idempotency_key}"
        cached = await redis.get(idem_cache_key)
        if cached is not None:
            return RunTriggerResponse.model_validate_json(cached)

    if await _already_in_flight(db, source):
        raise ApiError(
            409, "already_running", f"A run for '{id}' is already in progress"
        )

    if not body.force:
        breaker = get_breaker(source)
        if await breaker.state == CircuitState.OPEN:
            raise ApiError(
                503,
                "circuit_open",
                f"Circuit breaker for '{id}' is open — pass force=true to bypass",
            )

    now = datetime.now(UTC)
    response = RunTriggerResponse(
        run_id=_synthetic_run_id("run"),
        source_id=id,
        queued_at=now,
        estimated_start_at=now + timedelta(seconds=2),
        triggered_by=triggered_by,
        reason=reason,
        deduplicate=body.deduplicate,
        force=body.force,
    )

    if idem_cache_key:
        await redis.set(
            idem_cache_key, response.model_dump_json(), ex=IDEMPOTENCY_TTL_SECONDS
        )

    return response


async def run_in_background(registry_key: str, force: bool, triggered_by: str) -> None:
    """The actual work `trigger_run`'s caller schedules via
    `BackgroundTasks.add_task` after getting a 202 back. `deduplicate`
    isn't threaded through here — `load_to_postgres`'s `(pk) ON CONFLICT
    DO NOTHING` already makes re-fetched rows a no-op, which is the
    dedup behaviour every other ingest path (cron, CLI, backfill) already
    gets; there's no separate sha256-content-hash dedup mode to opt into.
    """
    try:
        await run_source(registry_key, triggered_by=triggered_by, bypass_breaker=force)
    except Exception as exc:
        log.error(
            "datasources.run_background_failed",
            registry_key=registry_key,
            error=str(exc),
        )


def _parse_chunk_seconds(chunk: str) -> int:
    seconds = _CHUNK_SECONDS.get(chunk)
    if seconds is None:
        raise ApiError(
            400,
            "invalid_range",
            f"Unsupported chunk '{chunk}' — expected one of {sorted(_CHUNK_SECONDS)}",
        )
    return seconds


async def _backfill_in_progress(redis: Redis, id: str) -> bool:
    return await redis.get(f"backfill:lock:{id}") is not None


async def trigger_backfill(
    redis: Redis,
    id: str,
    body: BackfillRequest,
    *,
    idempotency_key: str | None,
    triggered_by: str,
) -> BackfillTriggerResponse:
    require_catalog_entry(id)  # 404s if the id doesn't exist in the catalog

    if body.start >= body.end:
        raise ApiError(400, "invalid_range", "'start' must be before 'end'")
    now = datetime.now(UTC)
    if body.end > now:
        raise ApiError(400, "invalid_range", "'end' must not be in the future")
    if (body.end - body.start) > timedelta(days=_BACKFILL_MAX_DAYS):
        raise ApiError(
            400, "range_too_large", f"Range exceeds {_BACKFILL_MAX_DAYS} days"
        )

    idem_cache_key = None
    if idempotency_key:
        idem_cache_key = f"idempotency:datasources:{id}:backfill:{idempotency_key}"
        cached = await redis.get(idem_cache_key)
        if cached is not None:
            return BackfillTriggerResponse.model_validate_json(cached)

    if await _backfill_in_progress(redis, id):
        raise ApiError(
            409, "backfill_in_progress", f"A backfill for '{id}' is already running"
        )

    chunk_seconds = _parse_chunk_seconds(body.chunk)
    total_seconds = (body.end - body.start).total_seconds()
    total_chunks = max(1, math.ceil(total_seconds / chunk_seconds))
    estimated_duration_seconds = math.ceil(total_chunks / body.concurrency) * 60

    backfill_id = _synthetic_run_id("bf")

    response = BackfillTriggerResponse(
        backfill_id=backfill_id,
        source_id=id,
        queued_at=now,
        start=body.start,
        end=body.end,
        chunk=body.chunk,
        concurrency=body.concurrency,
        deduplicate=body.deduplicate,
        total_chunks=total_chunks,
        estimated_duration_seconds=estimated_duration_seconds,
        triggered_by=triggered_by,
        progress_url=f"/v1/ingestion/runs?backfill_id={backfill_id}",
    )

    lock_ttl = estimated_duration_seconds + 300
    await redis.set(f"backfill:lock:{id}", backfill_id, ex=lock_ttl, nx=True)

    if idem_cache_key:
        await redis.set(
            idem_cache_key, response.model_dump_json(), ex=IDEMPOTENCY_TTL_SECONDS
        )

    return response


async def run_backfill_in_background(
    redis: Redis, id: str, registry_key: str, start: datetime, end: datetime
) -> None:
    try:
        await run_backfill((registry_key,), start.date(), end.date())
    except Exception as exc:
        log.error(
            "datasources.backfill_background_failed", source_id=id, error=str(exc)
        )
    finally:
        await redis.delete(f"backfill:lock:{id}")
