"""`GET /v1/generation-mix` — per-fuel generation + emissions over a
period, from `raw_marts.fct_generation_mix`. Backs the Executive
Dashboard's "Emissions by Source" donut -- for the grid-electricity
(Scope 2) slice only. This platform has no Scope 1 (on-site fuel
combustion, refrigerants) or Scope 3 (supply chain, travel) data source
at all (see `TODO.md`'s Frontend TODO) -- this endpoint doesn't attempt
to serve those, only what's actually ingested."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_db, get_redis_client
from app.core.errors import ApiError
from app.core.config import Settings
from app.schemas.generation_mix import GenerationMixItem, GenerationMixResponse
from app.service.ml.data import load_generation_mix

router = APIRouter(prefix="/v1", tags=["generation-mix"])


@router.get("/generation-mix", response_model=GenerationMixResponse)
async def get_generation_mix(
    region: str | None = None,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> GenerationMixResponse:
    now = datetime.now(UTC)
    period_until = until or now
    period_since = since or datetime(period_until.year, 1, 1, tzinfo=UTC)

    # Same reasoning as `GET /v1/demand/summary`: explicit periods are
    # stable and cache on their own bounds; the default YTD-to-now period
    # keys on just the year so it's actually cacheable across requests.
    cache_key = (
        f"generation-mix:v1:{region}:{period_since.isoformat()}:{period_until.isoformat()}"
        if since is not None or until is not None
        else f"generation-mix:v1:{region}:ytd:{period_until.year}"
    )
    cached = await redis.get(cache_key)
    if cached is not None:
        return GenerationMixResponse.model_validate_json(cached)

    rows = await load_generation_mix(db, period_since, period_until, region)
    if not rows:
        raise ApiError(
            404,
            "not_found",
            "No generation-mix data available for that region/period",
        )

    total_generation_mwh = sum(
        float(r["total_generation_mwh"]) for r in rows if r["total_generation_mwh"]
    )
    total_emissions_kgco2e = sum(
        float(r["total_emissions_kgco2e"]) for r in rows if r["total_emissions_kgco2e"]
    )

    items = [
        GenerationMixItem(
            fuel_type=r["fuel_type"],
            category=r["category"],
            is_renewable=r["is_renewable"],
            total_generation_mwh=float(r["total_generation_mwh"] or 0),
            total_emissions_kgco2e=float(r["total_emissions_kgco2e"] or 0),
            pct_of_total_generation=(
                round(float(r["total_generation_mwh"]) / total_generation_mwh * 100, 2)
                if r["total_generation_mwh"] and total_generation_mwh
                else 0.0
            ),
        )
        for r in rows
    ]

    response = GenerationMixResponse(
        since=period_since,
        until=period_until,
        region=region,
        total_generation_mwh=total_generation_mwh,
        total_emissions_kgco2e=total_emissions_kgco2e,
        items=items,
    )
    await redis.set(
        cache_key, response.model_dump_json(), ex=settings.emissions_cache_ttl_seconds
    )
    return response
