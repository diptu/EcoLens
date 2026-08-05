"""Async job wrapper around `pipeline.backfill.backfill` for
`POST /v1/ingest/{source}/backfill` — the same `202`/job-id/Redis-lock/
progress-polling shape `POST /v1/data-sources/{id}/backfill` already
uses (`service.datasources.actions.trigger_backfill`/
`run_backfill_in_background`/`get_backfill_status`), adapted for a
plain `pipeline.tasks.registry.SOURCES` key instead of a catalog id —
no `CATALOG_BY_ID`/`require_catalog_entry` lookup needed here, `source`
is already validated as a `BackfillableSourceKey` by FastAPI before any
of this runs.

Deliberately a separate Redis key namespace
(`ingest_backfill:lock:{source}` / `ingest_backfill:result:{source}`)
from `datasources.actions`'s `backfill:lock:{id}` — different key shape
(registry key vs. catalog id) means the two can never collide, even for
the same underlying source triggered through both surfaces.

Unlike `datasources.actions`'s version, this also caches the finished
run's full day-by-day result (`_RESULT_TTL_SECONDS`) so a client polling
`GET .../backfill/status` after `running` flips back to `False` can
still see the outcome — `POST /v1/ingest/{source}/backfill` no longer
returns it directly now that it's backgrounded.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from redis.asyncio import Redis

from app.core.errors import ApiError
from app.core.logging import get_logger
from app.schemas.ingest import (
    BackfillableSourceKey,
    BackfillDayResult,
    IngestBackfillResponse,
    IngestBackfillStatusResponse,
    IngestBackfillTriggerResponse,
)
from app.service.pipeline.backfill import backfill as run_backfill

log = get_logger(__name__)

# Same cap the old synchronous endpoint enforced, and what `POST /v1/
# data-sources/{id}/backfill` uses (`actions._BACKFILL_MAX_DAYS`).
MAX_BACKFILL_DAYS = 90

# Result stays retrievable for an hour after a run finishes -- long
# enough for a client to notice `running` flipped and fetch it, short
# enough not to accumulate unbounded stale entries in Redis.
_RESULT_TTL_SECONDS = 3600


def _lock_key(source: str) -> str:
    return f"ingest_backfill:lock:{source}"


def _result_key(source: str) -> str:
    return f"ingest_backfill:result:{source}"


async def is_running(redis: Redis, source: BackfillableSourceKey) -> bool:
    return await redis.get(_lock_key(source)) is not None


async def get_status(
    redis: Redis, source: BackfillableSourceKey
) -> IngestBackfillStatusResponse:
    """Backs `GET /v1/ingest/{source}/backfill/status` — reads the same
    lock key `trigger` checks (so this is always consistent with the
    `409 backfill_in_progress` a concurrent trigger would get right
    now), falling back to the last cached result once the lock is gone.
    """
    lock_raw = await redis.get(_lock_key(source))
    if lock_raw is not None:
        return IngestBackfillStatusResponse(
            source=source,
            running=True,
            trigger=IngestBackfillTriggerResponse.model_validate_json(lock_raw),
        )

    result_raw = await redis.get(_result_key(source))
    if result_raw is not None:
        return IngestBackfillStatusResponse(
            source=source,
            running=False,
            result=IngestBackfillResponse.model_validate_json(result_raw),
        )

    return IngestBackfillStatusResponse(source=source, running=False)


async def trigger(
    redis: Redis,
    source: BackfillableSourceKey,
    start: date,
    end: date,
    lookback_minutes: int,
) -> IngestBackfillTriggerResponse:
    if start > end:
        raise ApiError(400, "invalid_range", "'start' must not be after 'end'")
    total_days = (end - start).days + 1
    if total_days > MAX_BACKFILL_DAYS:
        raise ApiError(
            400, "range_too_large", f"Range exceeds {MAX_BACKFILL_DAYS} days"
        )

    if await is_running(redis, source):
        raise ApiError(
            409,
            "backfill_in_progress",
            f"A backfill for '{source}' is already running",
        )

    response = IngestBackfillTriggerResponse(
        backfill_id=f"ibf-{uuid.uuid4().hex}",
        source=source,
        queued_at=datetime.now(UTC),
        start=start,
        end=end,
        total_days=total_days,
        lookback_minutes=lookback_minutes,
    )

    # One real day at a time, sequentially (`pipeline.backfill.backfill`)
    # -- a minute/day is a deliberately generous ceiling for the lock's
    # own TTL (a safety net against a crashed background task leaving
    # the lock stuck forever, not a real duration estimate), plus a
    # flat floor so even a 1-day range gets a sane minimum lifetime.
    lock_ttl = max(total_days * 60, 300)
    await redis.set(_lock_key(source), response.model_dump_json(), ex=lock_ttl, nx=True)
    return response


async def run_in_background(
    redis: Redis,
    source: BackfillableSourceKey,
    start: date,
    end: date,
    lookback_minutes: int,
) -> None:
    try:
        results = await run_backfill((source,), start, end, lookback_minutes)
        days = [
            BackfillDayResult(day=day, outcome=outcome)
            for (_, day), outcome in sorted(results.items(), key=lambda kv: kv[0][1])
        ]
        summary = IngestBackfillResponse(
            source=source,
            start=start,
            end=end,
            total_days=len(days),
            succeeded=sum(1 for d in days if d.outcome == "success"),
            skipped=sum(1 for d in days if d.outcome == "skipped"),
            failed=sum(1 for d in days if d.outcome.startswith("failed")),
            days=days,
        )
        await redis.set(
            _result_key(source), summary.model_dump_json(), ex=_RESULT_TTL_SECONDS
        )
    except Exception as exc:
        log.error("backfill_jobs.background_failed", source=source, error=str(exc))
    finally:
        await redis.delete(_lock_key(source))
