"""`GET /v1/demand/summary` — all-region period aggregate over
`raw_marts.fct_energy_demand`, backing the Executive Dashboard's
"Renewable Share" KPI and its "Avg Wholesale Price (YTD)" KPI (the
honestly-scoped replacement for the old mock "Cost Savings" figure --
see `TODO.md`'s Frontend TODO for why "savings" itself isn't computable
without a baseline/tariff model this platform doesn't have)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_db, get_redis_client
from app.core.errors import ApiError
from app.core.config import Settings
from app.schemas.demand import DemandSummaryResponse
from app.service.ml.data import load_demand_summary

router = APIRouter(prefix="/v1", tags=["demand"])


@router.get("/demand/summary", response_model=DemandSummaryResponse)
async def get_demand_summary(
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> DemandSummaryResponse:
    now = datetime.now(UTC)
    period_until = until or now
    period_since = since or datetime(period_until.year, 1, 1, tzinfo=UTC)

    # Explicit `since`/`until` are stable across calls, so cache on them
    # directly. The default (YTD-to-now) period isn't -- `now` moves every
    # request -- so key on just the year, same as `GET /v1/emissions/ytd`;
    # the cache TTL, not the key, governs how fresh "to now" actually is.
    cache_key = (
        f"demand:summary:v1:{period_since.isoformat()}:{period_until.isoformat()}"
        if since is not None or until is not None
        else f"demand:summary:v1:ytd:{period_until.year}"
    )
    cached = await redis.get(cache_key)
    if cached is not None:
        return DemandSummaryResponse.model_validate_json(cached)

    row = await load_demand_summary(db, period_since, period_until)
    if row is None:
        raise ApiError(404, "not_found", "No demand data available over that period")

    total_generation_mw = row["total_generation_mw"]
    total_renewable_mw = row["total_renewable_mw"]
    avg_price_mwh = row["avg_price_mwh"]

    response = DemandSummaryResponse(
        since=period_since,
        until=period_until,
        renewable_share_pct=(
            round(float(total_renewable_mw) / float(total_generation_mw) * 100, 2)
            if total_renewable_mw is not None
            and total_generation_mw is not None
            and total_generation_mw != 0
            else None
        ),
        avg_price_mwh=(
            round(float(avg_price_mwh), 2) if avg_price_mwh is not None else None
        ),
    )
    await redis.set(
        cache_key, response.model_dump_json(), ex=settings.emissions_cache_ttl_seconds
    )
    return response
