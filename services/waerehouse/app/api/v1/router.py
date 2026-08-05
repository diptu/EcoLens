from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.pipeline import router as pipeline_router

# Each resource router declares its own full `/v1/...` prefix -- this
# aggregator adds none of its own (same convention as ingestion/
# data-pipeline's identical `router.py`).
api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(pipeline_router)
