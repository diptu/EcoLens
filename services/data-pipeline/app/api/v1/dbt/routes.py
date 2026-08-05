"""dbt subcommand endpoints.

`POST /v1/dbt/{build,run,test}` runs the matching dbt subcommand against
this service's dbt project. `run_dbt` (ECO-D21) is a blocking subprocess
call, so it's offloaded via `asyncio.to_thread` to keep the event loop
free.

JWT-gated (admin only — this runs arbitrary dbt subcommands against the
warehouse) + `{"error": {...}}` envelope (`TODO.md`'s IAM section item
5) — this router predates `API_SPECEFICATIONS.md`'s auth convention and
used to have neither; now consistent with `/v1/data-sources*`.

`GET /v1/dbt/runs` — real `meta._dbt_build_log` history (TODO.md's
backfill section Follow-up item), open like `GET /v1/model/training-runs`
(read access to run history isn't the privileged part; running arbitrary
dbt subcommands is).
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_db
from app.core.errors import ApiError
from app.schemas.dbt import (
    DbtBuildRunsListResponse,
    DbtRunRequest,
    DbtRunResponse,
)
from app.core.security import Principal, require_roles
from app.core.config import Settings
from app.service.dbt_runner import run_dbt
from app.service.pipeline.dbt_build_log import (
    list_dbt_build_runs,
    log_dbt_build_finish,
    log_dbt_build_start,
)

router = APIRouter(prefix="/v1/dbt", tags=["dbt"])


@router.post("/{subcommand}", response_model=DbtRunResponse)
async def run_dbt_subcommand(
    subcommand: Literal["build", "run", "test"],
    body: DbtRunRequest = DbtRunRequest(),
    principal: Principal = Depends(require_roles("admin")),
    settings: Settings = Depends(get_app_settings),
) -> DbtRunResponse:
    target = body.target or settings.dbt_target

    # Doesn't go through `run_dbt_build_locked` -- this route runs
    # arbitrary subcommands/`extra_args`, not just a fixed `build`, so the
    # global build lock (built for serializing whole-`build` runs against
    # each other) doesn't apply here. Logged directly instead, same
    # `meta._dbt_build_log` table (`trigger="admin_api"`).
    log_id = await log_dbt_build_start(
        subcommand=subcommand,
        target=target,
        trigger="admin_api",
        triggered_by=principal.sub,
    )
    exit_code = await asyncio.to_thread(
        run_dbt, subcommand, settings.dbt_project_dir, target, body.extra_args
    )

    if exit_code != 0:
        await log_dbt_build_finish(
            log_id,
            status="failed",
            exit_code=exit_code,
            error=f"dbt {subcommand} exited {exit_code}",
        )
        raise ApiError(
            500, "internal", f"dbt {subcommand} failed with exit code {exit_code}"
        )

    await log_dbt_build_finish(log_id, status="success", exit_code=exit_code)
    return DbtRunResponse(subcommand=subcommand, target=target, exit_code=exit_code)


@router.get("/runs", response_model=DbtBuildRunsListResponse)
async def get_dbt_build_runs(
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> DbtBuildRunsListResponse:
    runs = await list_dbt_build_runs(db, limit)
    return DbtBuildRunsListResponse(data=runs)
