"""Ingestion endpoints.

`POST /v1/ingest/{source}` triggers the matching ingestion task and waits
for the fetch+DuckDB-stage+RabbitMQ-publish half to finish — same
synchronous-and-return-the-result convention as `api/routers/dbt.py` —
rather than fire-and-forget. Manual/dashboard-triggered (GitHub Actions'
scheduled runs call the CLI directly — `cli.py`'s `ingest` commands, see
their own module docstring — not this endpoint), so an immediate,
meaningful answer beats having to poll `GET /v1/ingest/runs` for that
much. The actual Postgres `raw.*` load happens asynchronously after this
returns (`overview.md` §2) — poll `GET /v1/ingest/runs` if you need to
know when that's done too.

Dispatch — including the "does this source land itself, or does the
caller need `standard_run` applied at call time?" distinction — is
entirely `app.service.pipeline.tasks.registry.run_source`'s job (built once,
shared with `cli.py`, ECO-D47/D73), not re-derived here.

JWT-gated + `{"error": {...}}` envelope (`TODO.md`'s IAM section item 5)
— this router predates `API_SPECEFICATIONS.md`'s auth convention and used
to have neither; now consistent with `/v1/data-sources*`.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import ApiError
from app.schemas.ingest import (
    IngestRequest,
    IngestRunSummary,
    IngestTriggerResponse,
)
from app.core.security import ROLES, Principal, require_roles
from app.service.pipeline.tasks.registry import run_source

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])

# Kept in sync with app.service.pipeline.tasks.registry.SOURCES' keys — see
# tests/test_ingest_router.py's drift check.
SourceKey = Literal["oe", "aemo-nem", "aemo-wem", "bom", "holidays"]


@router.post("/{source}", response_model=IngestTriggerResponse)
async def trigger_ingest(
    source: SourceKey,
    body: IngestRequest = IngestRequest(),
    _principal: Principal = Depends(require_roles("admin")),
) -> IngestTriggerResponse:
    kwargs: dict[str, int] = {}
    if body.lookback_minutes is not None:
        kwargs["lookback_minutes"] = body.lookback_minutes
    if body.year is not None:
        kwargs["year"] = body.year

    try:
        # kwargs only ever holds lookback_minutes/year (both int) -- mypy
        # can't see that statically against run_source's now-typed
        # triggered_by: str / bypass_breaker: bool keyword-only params,
        # since a bare dict[str, int] spread could in principle supply
        # either of those names too.
        rows = await run_source(source, **kwargs)  # type: ignore[arg-type]
    except Exception as exc:
        raise ApiError(500, "internal", f"ingest {source} failed: {exc}") from exc

    # `_common.standard_run` only takes the "success" (terminal) path
    # itself for an empty fetch (rows == 0) — anything else is "staged",
    # pending `pipeline.warehouse_sync`'s async Postgres load. Mirrors
    # that same branching here rather than threading a status value back
    # through `run_source`'s return type just for this.
    status = "success" if rows == 0 else "staged"
    return IngestTriggerResponse(source=source, status=status, rows_staged=rows)


@router.get("/runs", response_model=list[IngestRunSummary])
async def list_ingest_runs(
    limit: int = Query(default=20, ge=1, le=200),
    source: str | None = None,
    _principal: Principal = Depends(require_roles(*ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[IngestRunSummary]:
    query = (
        "SELECT id, source, status, started_at, finished_at, rows_loaded, error_message "
        "FROM meta._ingest_log"
    )
    params: dict[str, object] = {"limit": limit}
    if source:
        query += " WHERE source = :source"
        params["source"] = source
    query += " ORDER BY started_at DESC LIMIT :limit"

    result = await db.execute(text(query), params)
    rows = result.mappings().all()
    return [
        IngestRunSummary(
            run_id=str(row["id"]),
            source=row["source"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            rows_loaded=row["rows_loaded"],
            error=row["error_message"],
        )
        for row in rows
    ]
