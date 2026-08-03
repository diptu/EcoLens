from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.demand import router as demand_router
from app.api.v1.emissions import router as emissions_router
from app.api.v1.footprint import router as footprint_router
from app.api.v1.forecast import router as forecast_router
from app.api.v1.generation_mix import router as generation_mix_router
from app.api.v1.health import router as health_router
from app.api.v1.model import router as model_router
from app.api.v1.regions import router as regions_router
from app.api.v1.stream import router as stream_router

# Each resource router already declares its own `/v1` prefix (see each
# `routes.py`), so this aggregator adds none of its own -- matches
# data-pipeline's `api/v1/router.py` and preserves the deployed `/v1/...`
# URL contract (Dockerfile healthcheck, README's API reference).
api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(regions_router)
api_router.include_router(model_router)
api_router.include_router(emissions_router)
api_router.include_router(footprint_router)
api_router.include_router(forecast_router)
api_router.include_router(demand_router)
api_router.include_router(generation_mix_router)
api_router.include_router(stream_router)
