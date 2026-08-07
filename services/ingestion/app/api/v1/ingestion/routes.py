"""`GET /v1/ingestion/runs/{id}` — look up a single ingestion run by its
own `meta._ingest_log` run id (a UUID), regardless of which source it
belongs to. Distinct from `GET /v1/data-sources/{id}/history` (paginated,
scoped to one catalog id/source) — this is the "I have a run id, give me
its full record" lookup, e.g. the id `POST /v1/data-sources/{id}/run`'s
`RunTriggerResponse` doesn't actually return (that response's `run_id`
is a synthetic trigger id, not this one — see that schema's own
docstring) but `POST /v1/ingest/{source}` and the CLI both cause a real
one to exist.

`GET /v1/ingestion/public/{pipelines,runs}` (2026-08-07,
`services/ingestion/TODO.md`'s "Frontend integration" section) — this
service's own equivalent of `services/data-pipeline`'s identically-named
routes, which is what `services/dashboard` currently calls instead
(nothing here yet). See `app.service.public_pipelines`'s own module
docstring for what's the same/different about the query logic, and
`app.schemas.ingest.public`'s docstrings for what's the same/different
about the response shape. Named `/public/*` for API-shape parity with
data-pipeline's routes (a real client switching between the two sees
the same path suffix) even though, unlike data-pipeline, there's no
non-public authenticated twin here to distinguish these *from* —
every route in this service is already open (see below).

Open — no auth required for now, matching every other route in this
service's current state.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.schemas.ingest import (
    IngestionRunOut,
    PublicPipelinesListResponse,
    PublicRunsListResponse,
)
from app.service.ingest_runs import get_ingest_run
from app.service.public_pipelines import list_pipelines_public, list_runs_public

router = APIRouter(prefix="/v1/ingestion", tags=["ingestion"])


@router.get("/runs/{id}", response_model=IngestionRunOut)
async def get_ingestion_run_endpoint(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> IngestionRunOut:
    return await get_ingest_run(db, id)


@router.get("/public/pipelines", response_model=PublicPipelinesListResponse)
async def list_pipelines_public_endpoint(
    db: AsyncSession = Depends(get_db),
) -> PublicPipelinesListResponse:
    return await list_pipelines_public(db)


@router.get("/public/runs", response_model=PublicRunsListResponse)
async def list_runs_public_endpoint(
    source_id: str | None = None,
    status: str | None = None,
    trigger: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> PublicRunsListResponse:
    return await list_runs_public(
        db,
        source_id=source_id,
        status=status,
        trigger=trigger,
        from_=from_,
        to=to,
        limit=limit,
        cursor=cursor,
    )
