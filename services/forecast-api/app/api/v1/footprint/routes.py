"""`POST /v1/footprint` (`README.md` § API reference) — kgCO2e for a
given `kwh` over a `period`, using the generation-weighted average
carbon intensity across that period (`service/ml/data.py`'s
`load_intensity_over_period`). `todo-model-training.md` Phase 7: real
external-provider-first with derived (`live_mix_weighted`) fallback,
same as `/v1/emissions`'s routes -- see that module's `_resolve_row_
intensity` (mirrored here, not imported across router modules, matching
this codebase's per-module-boundary convention elsewhere)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_db, get_redis_client
from app.core.errors import ApiError
from app.schemas.footprint import FootprintRequest, FootprintResponse
from app.core.config import Settings
from app.service.ml.data import (
    IntensityMethod,
    load_intensity_over_period,
    resolve_intensity_method,
)

router = APIRouter(prefix="/v1", tags=["footprint"])


def _resolve_intensity(row: dict, settings: Settings) -> tuple[float, IntensityMethod]:
    """`todo-model-training.md` Phase 7's real fallback, for this one
    call site -- mirrors `emissions/routes.py`'s `_resolve_row_intensity`
    (not imported across router modules; small enough, and each router
    module already owns its own response-building logic independently
    elsewhere in this codebase)."""
    provider_generation_mwh = row.get("provider_generation_mwh")
    provider_emissions_kgco2e = row.get("provider_emissions_kgco2e")
    provider_intensity = (
        float(provider_emissions_kgco2e) / float(provider_generation_mwh)
        if provider_generation_mwh not in (None, 0)
        and provider_emissions_kgco2e is not None
        else None
    )
    latest_hour = row.get("latest_hour")
    method = (
        resolve_intensity_method(
            latest_hour,
            provider_intensity,
            settings.emissions_provider_freshness_minutes,
        )
        if latest_hour is not None
        else "live_mix_weighted"
    )
    if method == "live_provider" and provider_intensity is not None:
        return provider_intensity, method
    derived = float(row["total_emissions_kgco2e"]) / float(row["total_generation_mwh"])
    return derived, "live_mix_weighted"


def _parse_period(period: str) -> tuple[datetime, datetime]:
    """`"start/end"` ISO 8601 interval notation (`README.md`'s own
    example: `"2026-07-01T00:00Z/2026-07-31T23:59Z"`) — not a general
    ISO-8601 duration/interval parser (no `PnYnMnD` duration half, no
    repeating-interval `R n/` prefix), just the two-timestamps case this
    endpoint actually needs."""
    parts = period.split("/")
    if len(parts) != 2:
        raise ApiError(
            400, "invalid_period", f"'{period}' is not a valid 'start/end' period"
        )
    try:
        start = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
        end = datetime.fromisoformat(parts[1].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(
            400, "invalid_period", f"'{period}' is not a valid 'start/end' period"
        ) from exc
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if start >= end:
        raise ApiError(400, "invalid_period", "period start must be before its end")
    return start, end


@router.post("/footprint", response_model=FootprintResponse)
async def compute_footprint(
    body: FootprintRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> FootprintResponse:
    start, end = _parse_period(body.period)

    cache_key = (
        f"footprint:v1:{body.region}:{start.isoformat()}:{end.isoformat()}:{body.kwh}"
    )
    cached = await redis.get(cache_key)
    if cached is not None:
        return FootprintResponse.model_validate_json(cached)

    row = await load_intensity_over_period(db, body.region, start, end)
    if row is None:
        raise ApiError(
            404,
            "not_found",
            f"No carbon-intensity data available for region '{body.region}' over that period",
        )

    intensity_kgco2e_per_mwh, method = _resolve_intensity(row, settings)
    intensity_kg_co2e_per_kwh = intensity_kgco2e_per_mwh / 1000
    kg_co2e = body.kwh * intensity_kg_co2e_per_kwh

    response = FootprintResponse(
        region=body.region,
        kwh=body.kwh,
        method=method,
        kg_co2e=round(kg_co2e, 3),
        intensity_kg_co2e_per_kwh=round(intensity_kg_co2e_per_kwh, 6),
        factors_version=row["factors_version"],
    )
    await redis.set(
        cache_key, response.model_dump_json(), ex=settings.footprint_cache_ttl_seconds
    )
    return response
