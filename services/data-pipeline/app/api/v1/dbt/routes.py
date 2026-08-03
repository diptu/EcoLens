"""dbt subcommand endpoints.

`POST /v1/dbt/{build,run,test}` runs the matching dbt subcommand against
this service's dbt project. `run_dbt` (ECO-D21) is a blocking subprocess
call, so it's offloaded via `asyncio.to_thread` to keep the event loop
free.

JWT-gated (admin only — this runs arbitrary dbt subcommands against the
warehouse) + `{"error": {...}}` envelope (`TODO.md`'s IAM section item
5) — this router predates `API_SPECEFICATIONS.md`'s auth convention and
used to have neither; now consistent with `/v1/data-sources*`.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends

from app.api.v1.deps import get_app_settings
from app.core.errors import ApiError
from app.schemas.dbt import DbtRunRequest, DbtRunResponse
from app.core.security import Principal, require_roles
from app.core.config import Settings
from app.service.dbt_runner import run_dbt

router = APIRouter(prefix="/v1/dbt", tags=["dbt"])


@router.post("/{subcommand}", response_model=DbtRunResponse)
async def run_dbt_subcommand(
    subcommand: Literal["build", "run", "test"],
    body: DbtRunRequest = DbtRunRequest(),
    _principal: Principal = Depends(require_roles("admin")),
    settings: Settings = Depends(get_app_settings),
) -> DbtRunResponse:
    target = body.target or settings.dbt_target

    exit_code = await asyncio.to_thread(
        run_dbt, subcommand, settings.dbt_project_dir, target, body.extra_args
    )

    if exit_code != 0:
        raise ApiError(
            500, "internal", f"dbt {subcommand} failed with exit code {exit_code}"
        )

    return DbtRunResponse(subcommand=subcommand, target=target, exit_code=exit_code)
