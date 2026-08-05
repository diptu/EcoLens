"""`POST /v1/ingest/{source}` and `POST /v1/ingest/{source}/backfill` —
the direct "just ingest it" endpoints. `{source}` is a `pipeline.tasks.
registry.SOURCES` key (`oe`, `aemo-nem`, `aemo-wem`, `bom`, `holidays`)
— not a catalog id (`ds-oe`, ...), unlike `POST /v1/data-sources/{id}/
run`/`.../backfill`.

`POST /v1/ingest/{source}` is synchronous — awaits the real fetch and
returns the actual outcome, same one-shot-CLI-equivalent contract as
`ecolens-ingestion ingest <source>` (`app/cli.py`), just over HTTP. A
single source's ingest is fast enough (seconds) that blocking the
request is fine.

`POST /v1/ingest/{source}/backfill` is **not** — a multi-day range run
one-day-at-a-time (`pipeline.backfill.backfill`) can take long enough
that blocking risks a proxy/client timeout, so it's `202` + a
`backfill_id` + background execution instead
(`service.pipeline.backfill_jobs`), poll `GET /v1/ingest/{source}/
backfill/status` for progress/result — the same shape `POST /v1/data-
sources/{id}/backfill` already uses, just keyed by registry `source`
instead of a catalog id.

`source` is typed as `IngestSourceKey`/`BackfillableSourceKey` (a
`Literal`, not a bare `str`) so the interactive API docs (`/docs`)
render it as an actual dropdown instead of a free-text box — same
convention `app.api.v1.datasources.routes`'s `SortField`/`Order`/
`Category` query params already use. FastAPI validates it against that
`Literal` before either handler ever runs, so an unknown source is a
standard `422` (same shape every other `Literal`-typed param in this
API already produces), not a hand-rolled `404`.

Open — no auth required for now, matching every other route in this
service's current state (`app.api.v1.datasources.routes`'s own module
docstring).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from redis.asyncio import Redis

from app.api.v1.deps import get_redis_client
from app.core.errors import ApiError
from app.core.logging import get_logger
from app.schemas.ingest import (
    BackfillableSourceKey,
    IngestBackfillRequest,
    IngestBackfillStatusResponse,
    IngestBackfillTriggerResponse,
    IngestRequest,
    IngestResponse,
    IngestSourceKey,
)
from app.service.pipeline import backfill_jobs
from app.service.pipeline.tasks.registry import run_source

log = get_logger(__name__)

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])


@router.post("/{source}", response_model=IngestResponse)
async def ingest_source_endpoint(
    source: IngestSourceKey,
    body: IngestRequest = IngestRequest(),
) -> IngestResponse:
    call_kwargs: dict[str, Any] = {}
    if body.lookback_minutes is not None:
        call_kwargs["lookback_minutes"] = body.lookback_minutes
    if body.year is not None:
        call_kwargs["year"] = body.year

    try:
        rows_staged = await run_source(
            source, triggered_by=body.triggered_by, **call_kwargs
        )
    except Exception as exc:
        log.error("ingest_endpoint.failed", source=source, error=str(exc))
        raise ApiError(502, "ingest_failed", str(exc)) from exc

    return IngestResponse(
        source=source, rows_staged=rows_staged, triggered_by=body.triggered_by
    )


@router.post(
    "/{source}/backfill",
    response_model=IngestBackfillTriggerResponse,
    status_code=202,
)
async def ingest_backfill_endpoint(
    source: BackfillableSourceKey,
    body: IngestBackfillRequest,
    background_tasks: BackgroundTasks,
    redis: Redis = Depends(get_redis_client),
) -> IngestBackfillTriggerResponse:
    response = await backfill_jobs.trigger(
        redis, source, body.start, body.end, body.lookback_minutes
    )
    background_tasks.add_task(
        backfill_jobs.run_in_background,
        redis,
        source,
        body.start,
        body.end,
        body.lookback_minutes,
    )
    return response


@router.get("/{source}/backfill/status", response_model=IngestBackfillStatusResponse)
async def ingest_backfill_status_endpoint(
    source: BackfillableSourceKey,
    redis: Redis = Depends(get_redis_client),
) -> IngestBackfillStatusResponse:
    return await backfill_jobs.get_status(redis, source)
