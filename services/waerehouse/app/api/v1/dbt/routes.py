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
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_log_db, get_redis_client
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.response_cache import cached_response
from app.dbt.scheduler import run_build
from app.schemas.dbt import DbtBuildRunOut, DbtBuildRunsListResponse, DbtRunResponse

router = APIRouter(prefix="/v1/dbt", tags=["dbt"])

# `DbtBuildRunOut | None` (`GET /build/last`) doesn't fit `app.core.
# response_cache.cached_response`'s non-optional `model_cls` signature --
# a real "no build has ever run" `None` needs its own sentinel to
# round-trip through Redis (a bare empty string would be indistinguishable
# from "not cached yet"), so that one endpoint below caches inline instead
# of through the shared helper.
_NO_BUILD_SENTINEL = "__none__"


@router.post("/build", response_model=DbtRunResponse)
async def trigger_dbt_build(db: AsyncSession = Depends(get_log_db)) -> DbtRunResponse:
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
async def last_dbt_build(
    db: AsyncSession = Depends(get_log_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> DbtBuildRunOut | None:
    """Most recent `meta._dbt_build_log` row, any `subcommand` -- backs
    the Pipeline Operations tab's dbt-warehouse-transform row (last
    run/status). `GET /build/runs` below is the full history list --
    this stays a thin, single-row convenience wrapper over it rather
    than being removed, since it's cheaper for a caller that only ever
    wants "what's the current state" to not have to slice a list.

    Cached (2026-08-11, real fix for a real measured problem): confirmed
    live at ~2.5s/call with no caching at all before this -- see
    `app.core.response_cache`'s own module docstring for why. Short TTL
    (`dbt_build_status_cache_ttl_seconds`, 5s): this backs live
    build-status polling, so a bounded few-second staleness window is
    the real, disclosed tradeoff for a fast response here, not
    fabricated data.
    """
    cache_key = "waerehouse:dbt_build_last:v1"
    cached = await redis.get(cache_key)
    if cached is not None:
        return None if cached == _NO_BUILD_SENTINEL else DbtBuildRunOut.model_validate_json(cached)

    result = await db.execute(
        text(
            "SELECT id, subcommand, target, trigger, triggered_by, status, "
            "started_at, finished_at, exit_code, error "
            "FROM meta._dbt_build_log ORDER BY started_at DESC LIMIT 1"
        )
    )
    row = result.mappings().first()
    if row is None:
        await redis.set(cache_key, _NO_BUILD_SENTINEL, ex=settings.dbt_build_status_cache_ttl_seconds)
        return None
    response = DbtBuildRunOut(**{**dict(row), "id": str(row["id"])})
    await redis.set(cache_key, response.model_dump_json(), ex=settings.dbt_build_status_cache_ttl_seconds)
    return response


@router.get("/build/runs", response_model=DbtBuildRunsListResponse)
async def list_dbt_build_runs_endpoint(
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_log_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
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
    privileged part.

    Cached, same real reasoning/TTL as `GET /build/last` above.
    """
    async def _load() -> DbtBuildRunsListResponse:
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

    return await cached_response(
        redis,
        f"waerehouse:dbt_build_runs:v1:{limit}",
        settings.dbt_build_status_cache_ttl_seconds,
        DbtBuildRunsListResponse,
        _load,
    )
