"""`GET /v1/ingestion/runs/{id}` — look up a single ingestion run by its
own `meta._ingest_log` run id (a UUID), regardless of which source it
belongs to. Distinct from `GET /v1/data-sources/{id}/history` (paginated,
scoped to one catalog id/source) — this is the "I have a run id, give me
its full record" lookup, e.g. the id `POST /v1/data-sources/{id}/run`'s
`RunTriggerResponse` doesn't actually return (that response's `run_id`
is a synthetic trigger id, not this one — see that schema's own
docstring) but `POST /v1/ingest/{source}` and the CLI both cause a real
one to exist.

Open — no auth required for now, matching every other route in this
service's current state.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.schemas.ingest import IngestionRunOut
from app.service.ingest_runs import get_ingest_run

router = APIRouter(prefix="/v1/ingestion", tags=["ingestion"])


@router.get("/runs/{id}", response_model=IngestionRunOut)
async def get_ingestion_run_endpoint(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> IngestionRunOut:
    return await get_ingest_run(db, id)
