"""FastAPI app factory for data-pipeline's own internal control API --
mounts the forecasting control surface (`ecolens.forecasting.api`), the
ingestion control surface (`ecolens.ingestion.api`), and the warehouse
pipeline control surface (`ecolens.warehouse.runner.api`). Internal
only: `forecast-api` never calls this (see `forecasting/api.py`'s
module docstring); it's for manually/cron-triggering training,
historical backfills, and dbt warehouse runs without shell access to
this repo.

Run via `make pipeline` (`uvicorn ecolens.api.app:app --reload --port 8001`).
"""

from __future__ import annotations

from fastapi import FastAPI

from ecolens.forecasting.api import router as forecasting_router
from ecolens.ingestion.api import router as ingestion_router
from ecolens.warehouse.runner.api import router as warehouse_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="ecoLens Data-Pipeline Control API",
        version="1.0.0",
        description=(
            "Internal control surface for the forecasting pipeline, "
            "historical-ingestion backfills, and the warehouse (dbt) "
            "pipeline. Not a public contract."
        ),
    )
    app.include_router(forecasting_router)
    app.include_router(ingestion_router)
    app.include_router(warehouse_router)
    return app


app = create_app()

__all__ = ["create_app", "app"]
