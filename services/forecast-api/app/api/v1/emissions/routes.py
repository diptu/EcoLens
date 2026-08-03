"""`GET /v1/emissions` (`README.md` § API reference) — live carbon
intensity for a region, from `raw_marts.fct_carbon_intensity`'s most
recent hour (`data-pipeline`'s dbt project, README's `live_mix_weighted`
method).

`GET /v1/emissions/ytd` — all-region rollup from the start of the
current calendar year (UTC) to now, backing the dashboard's Executive
Dashboard "Total CO2e (YTD)" KPI.

`GET /v1/emissions/current` — all-region rollup of each region's own
latest hour, backing the "Carbon Intensity" KPI + "Emissions Snapshot"
preview.

`GET /v1/emissions/timeseries` — all-region actual emissions bucketed by
hour or day, backing the "Emissions Snapshot" sparkline and the
"Emissions Trend" chart's actual half.

`GET /v1/emissions/forecast` — see `get_emissions_forecast`'s own
docstring for the methodology (demand forecast x current intensity)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    get_app_settings,
    get_db,
    get_model_registry,
    get_redis_client,
)
from app.api.v1.forecast.routes import (
    _forecast_arrays_nem,
    _forecast_arrays_single_region,
    _format_timedelta,
)
from app.core.errors import ApiError
from app.schemas.emissions import (
    EmissionsCurrentResponse,
    EmissionsForecastPoint,
    EmissionsForecastResponse,
    EmissionsResponse,
    EmissionsTimeseriesPoint,
    EmissionsTimeseriesResponse,
    EmissionsYtdResponse,
)
from app.core.config import Settings
from app.service.ml.data import (
    load_current_intensity,
    load_emissions_timeseries,
    load_latest_intensity,
    load_ytd_intensity,
)
from app.service.ml.registry import ModelRegistry

router = APIRouter(prefix="/v1", tags=["emissions"])


@router.get("/emissions", response_model=EmissionsResponse)
async def get_emissions(
    region: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> EmissionsResponse:
    cache_key = f"emissions:v1:{region}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return EmissionsResponse.model_validate_json(cached)

    row = await load_latest_intensity(db, region)
    if row is None:
        raise ApiError(
            404,
            "not_found",
            f"No carbon-intensity data available for region '{region}'",
        )

    response = EmissionsResponse(
        region=region,
        as_of=row["hour"] if row["hour"].tzinfo else row["hour"].replace(tzinfo=UTC),
        intensity_kgco2e_per_mwh=(
            float(row["intensity_kgco2e_per_mwh"])
            if row["intensity_kgco2e_per_mwh"] is not None
            else None
        ),
        total_generation_mwh=(
            float(row["total_generation_mwh"])
            if row["total_generation_mwh"] is not None
            else None
        ),
        total_emissions_kgco2e=(
            float(row["total_emissions_kgco2e"])
            if row["total_emissions_kgco2e"] is not None
            else None
        ),
        factors_version=row["factors_version"],
    )
    await redis.set(
        cache_key, response.model_dump_json(), ex=settings.emissions_cache_ttl_seconds
    )
    return response


@router.get("/emissions/ytd", response_model=EmissionsYtdResponse)
async def get_emissions_ytd(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> EmissionsYtdResponse:
    now = datetime.now(UTC)
    since = datetime(now.year, 1, 1, tzinfo=UTC)

    cache_key = f"emissions:ytd:v1:{now.year}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return EmissionsYtdResponse.model_validate_json(cached)

    row = await load_ytd_intensity(db, since, now)
    if row is None:
        raise ApiError(
            404,
            "not_found",
            "No carbon-intensity data available year-to-date",
        )

    total_generation_mwh = (
        float(row["total_generation_mwh"])
        if row["total_generation_mwh"] is not None
        else None
    )
    total_emissions_kgco2e = (
        float(row["total_emissions_kgco2e"])
        if row["total_emissions_kgco2e"] is not None
        else None
    )

    response = EmissionsYtdResponse(
        since=since,
        until=now,
        total_generation_mwh=total_generation_mwh,
        total_emissions_kgco2e=total_emissions_kgco2e,
        total_emissions_tco2e=(
            total_emissions_kgco2e / 1000
            if total_emissions_kgco2e is not None
            else None
        ),
        intensity_kgco2e_per_mwh=(
            total_emissions_kgco2e / total_generation_mwh
            if total_emissions_kgco2e is not None
            and total_generation_mwh is not None
            and total_generation_mwh != 0
            else None
        ),
        factors_version=row["factors_version"],
    )
    await redis.set(
        cache_key,
        response.model_dump_json(),
        ex=settings.emissions_ytd_cache_ttl_seconds,
    )
    return response


@router.get("/emissions/current", response_model=EmissionsCurrentResponse)
async def get_emissions_current(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> EmissionsCurrentResponse:
    cache_key = "emissions:current:v1"
    cached = await redis.get(cache_key)
    if cached is not None:
        return EmissionsCurrentResponse.model_validate_json(cached)

    row = await load_current_intensity(db)
    if row is None:
        raise ApiError(
            404, "not_found", "No carbon-intensity data available for any region"
        )

    total_generation_mwh = (
        float(row["total_generation_mwh"])
        if row["total_generation_mwh"] is not None
        else None
    )
    total_emissions_kgco2e = (
        float(row["total_emissions_kgco2e"])
        if row["total_emissions_kgco2e"] is not None
        else None
    )
    as_of = row["as_of"]
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)

    response = EmissionsCurrentResponse(
        as_of=as_of,
        total_generation_mwh=total_generation_mwh,
        total_emissions_kgco2e=total_emissions_kgco2e,
        intensity_kgco2e_per_mwh=(
            total_emissions_kgco2e / total_generation_mwh
            if total_emissions_kgco2e is not None
            and total_generation_mwh is not None
            and total_generation_mwh != 0
            else None
        ),
        factors_version=row["factors_version"],
    )
    await redis.set(
        cache_key, response.model_dump_json(), ex=settings.emissions_cache_ttl_seconds
    )
    return response


@router.get("/emissions/timeseries", response_model=EmissionsTimeseriesResponse)
async def get_emissions_timeseries(
    bucket: Literal["hour", "day"] = "hour",
    days: int = Query(default=1, ge=1, le=366),
    region: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> EmissionsTimeseriesResponse:
    now = datetime.now(UTC)
    since = now - timedelta(days=days)

    cache_key = (
        f"emissions:timeseries:v1:{bucket}:{days}:{region}:{now.strftime('%Y%m%d%H')}"
    )
    cached = await redis.get(cache_key)
    if cached is not None:
        return EmissionsTimeseriesResponse.model_validate_json(cached)

    rows = await load_emissions_timeseries(db, since, now, bucket, region)

    factors_version = None
    points = []
    for row in rows:
        factors_version = row["factors_version"] or factors_version
        bucket_ts = row["bucket"]
        if bucket_ts.tzinfo is None:
            bucket_ts = bucket_ts.replace(tzinfo=UTC)
        points.append(
            EmissionsTimeseriesPoint(
                bucket=bucket_ts,
                total_generation_mwh=(
                    float(row["total_generation_mwh"])
                    if row["total_generation_mwh"] is not None
                    else None
                ),
                total_emissions_kgco2e=(
                    float(row["total_emissions_kgco2e"])
                    if row["total_emissions_kgco2e"] is not None
                    else None
                ),
                intensity_kgco2e_per_mwh=(
                    float(row["intensity_kgco2e_per_mwh"])
                    if row["intensity_kgco2e_per_mwh"] is not None
                    else None
                ),
            )
        )

    response = EmissionsTimeseriesResponse(
        since=since,
        until=now,
        bucket=bucket,
        region=region,
        factors_version=factors_version,
        points=points,
    )
    await redis.set(
        cache_key,
        response.model_dump_json(),
        ex=settings.emissions_cache_ttl_seconds,
    )
    return response


@router.get("/emissions/forecast", response_model=EmissionsForecastResponse)
async def get_emissions_forecast(
    region: str = "NEM",
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    registry: ModelRegistry = Depends(get_model_registry),
    settings: Settings = Depends(get_app_settings),
) -> EmissionsForecastResponse:
    """Projects an emissions band by applying the *current* carbon
    intensity to `GET /v1/forecast`'s demand P10/P50/P90 -- there is no
    learned emissions-forecasting model in this service, and holding
    intensity constant across the horizon is a real methodological
    choice (documented, not hidden): the fuel mix driving intensity can
    shift meaningfully over a multi-hour horizon (e.g. solar dropping off
    at dusk), so this is a reasonable near-term approximation, not a
    substitute for a proper mix-aware emissions forecast."""
    bundle = registry.bundle
    if bundle is None:
        raise ApiError(
            503, "model_not_loaded", "No Production model version is loaded yet"
        )

    cache_key = f"emissions:forecast:v1:{region}:{bundle.version}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return EmissionsForecastResponse.model_validate_json(cached)

    if region == "NEM":
        lo, p50, hi, step, last_ts = await _forecast_arrays_nem(db, bundle)
        intensity_row = await load_current_intensity(db)
    else:
        lo, p50, hi, step, last_ts = await _forecast_arrays_single_region(
            db, bundle, region
        )
        intensity_row = await load_latest_intensity(db, region)

    if intensity_row is None or not intensity_row.get("total_generation_mwh"):
        raise ApiError(
            404,
            "not_found",
            f"No current carbon-intensity data available for '{region}' "
            "to project an emissions forecast from",
        )
    intensity = float(intensity_row["total_emissions_kgco2e"]) / float(
        intensity_row["total_generation_mwh"]
    )
    step_hours = step.total_seconds() / 3600

    points = [
        EmissionsForecastPoint(
            ts=last_ts + step * (i + 1),
            p10_kgco2e=round(float(lo[0, i]) * step_hours * intensity, 1),
            p50_kgco2e=round(float(p50[0, i]) * step_hours * intensity, 1),
            p90_kgco2e=round(float(hi[0, i]) * step_hours * intensity, 1),
        )
        for i in range(bundle.horizon)
    ]

    response = EmissionsForecastResponse(
        region=region,
        generated_at=datetime.now(UTC),
        horizon=_format_timedelta(step * bundle.horizon),
        interval=_format_timedelta(step),
        intensity_kgco2e_per_mwh=round(intensity, 3),
        factors_version=intensity_row["factors_version"],
        points=points,
    )
    await redis.set(
        cache_key, response.model_dump_json(), ex=settings.forecast_cache_ttl_seconds
    )
    return response
