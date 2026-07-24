"""FastAPI app factory for data-pipeline's own internal control API --
mounts the forecasting control surface (`ecolens.forecasting.api`) and
the ingestion control surface (`ecolens.ingestion.api`). Internal only:
`forecast-api` never calls this (see `forecasting/api.py`'s module
docstring); it's for manually/cron-triggering training and historical
Mongo backfills without shell access to this repo.

Run via `make pipeline` (`uvicorn ecolens.api.app:app --reload --port 8001`).
"""

from __future__ import annotations

from fastapi import FastAPI

from ecolens.forecasting.api import router as forecasting_router
from ecolens.ingestion.api import router as ingestion_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="ecoLens Data-Pipeline Control API",
        version="1.0.0",
        description=(
            "Internal control surface for the forecasting pipeline and "
            "historical-ingestion backfills. Not a public contract."
        ),
    )
    app.include_router(forecasting_router)
    app.include_router(ingestion_router)
    return app


app = create_app()

__all__ = ["create_app", "app"]
