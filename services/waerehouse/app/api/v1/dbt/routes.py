"""`POST /v1/dbt/build` -- the "Trigger Build" action for the dashboard's
Pipeline Operations tab's dbt-warehouse-transform row. Deliberately open
(no auth), synchronous (`dbt build` typically finishes well under a
minute).

No admin-gated arbitrary-subcommand endpoint here -- this service's CLI
(`ecolens-warehouse dbt <subcommand>`) already covers that for an
operator with shell access; a fixed, no-args `build` trigger is the only
HTTP surface this route adds.

The actual lock-acquire / run / log-finish / training-trigger-publish
sequence lives in `app.dbt.scheduler.run_build` -- shared with the
automatic post-landed-event trigger (`consumers.landed_events`,
`TODO.md`'s "Scheduled Execution Runner"), so there's exactly one
Postgres-native concurrent-build lock (an atomic `INSERT ... WHERE NOT
EXISTS` against `meta._dbt_build_log`, no Redis dependency needed) both
triggers go through, not two copies that could drift. See that module's
own docstring for the full lock/staleness reasoning.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import ApiError
from app.dbt.scheduler import run_build
from app.schemas.dbt import DbtBuildRunOut, DbtBuildRunsListResponse, DbtRunResponse

router = APIRouter(prefix="/v1/dbt", tags=["dbt"])


@router.post("/build", response_model=DbtRunResponse)
async def trigger_dbt_build(db: AsyncSession = Depends(get_db)) -> DbtRunResponse:
    target = "dev"
    outcome = await run_build(
        db, trigger="dashboard_manual", triggered_by="dashboard", target=target
    )
    if outcome is None:
        raise ApiError(
            409,
            "dbt_build_in_progress",
            "Another dbt build is already running -- wait for it to finish before triggering another.",
        )
    exit_code, _run_id = outcome
    return DbtRunResponse(subcommand="build", target=target, exit_code=exit_code)


@router.get("/build/last", response_model=DbtBuildRunOut | None)
async def last_dbt_build(db: AsyncSession = Depends(get_db)) -> DbtBuildRunOut | None:
    """Most recent `meta._dbt_build_log` row, any `subcommand` -- backs
    the Pipeline Operations tab's dbt-warehouse-transform row (last
    run/status). `GET /build/runs` below is the full history list --
    this stays a thin, single-row convenience wrapper over it rather
    than being removed, since it's cheaper for a caller that only ever
    wants "what's the current state" to not have to slice a list."""
    result = await db.execute(
        text(
            "SELECT id, subcommand, target, trigger, triggered_by, status, "
            "started_at, finished_at, exit_code, error "
            "FROM meta._dbt_build_log ORDER BY started_at DESC LIMIT 1"
        )
    )
    row = result.mappings().first()
    if row is None:
        return None
    return DbtBuildRunOut(**{**dict(row), "id": str(row["id"])})


@router.get("/build/runs", response_model=DbtBuildRunsListResponse)
async def list_dbt_build_runs_endpoint(
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> DbtBuildRunsListResponse:
    """Real `meta._dbt_build_log` history, newest first -- the same real
    "is a build in flight right now" signal (a `status == "running"`
    row) `GET /v1/model/training-runs` gives for training, and the
    endpoint the dashboard's Operational Tasks page needs for live
    build-status polling / a real 24h success-rate aggregate for the
    dbt row instead of `GET /build/last`'s single-row 0%/100% proxy
    (`services/waerehouse/TODO.md`'s own note on that gap). Open, no
    auth -- same reasoning `GET /build/last` and `GET /v1/model/
    training-runs` already use: read access to run history isn't the
    privileged part."""
    result = await db.execute(
        text(
            "SELECT id, subcommand, target, trigger, triggered_by, status, "
            "started_at, finished_at, exit_code, error "
            "FROM meta._dbt_build_log ORDER BY started_at DESC LIMIT :limit"
        ),
        {"limit": limit},
    )
    rows = result.mappings().all()
    return DbtBuildRunsListResponse(
        data=[
            DbtBuildRunOut(**{**dict(row), "id": str(row["id"])})
            for row in rows
        ]
    )
