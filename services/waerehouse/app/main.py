"""FastAPI application factory for the warehouse service.

Served by `uvicorn app.main:app`. `create_app()` exists separately from
the module-level `app` so tests can build a fresh instance per test if
they need to -- same shape as ingestion/data-pipeline's identical module.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import ApiError, api_error_handler
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestIdMiddleware
from app.core.tracing import configure_tracing
from app.db.rabbitmq import close_rabbitmq
from app.db.session import dispose, get_engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    configure_tracing()
    get_engine()  # eagerly build the connection pool rather than on first request

    logger.info("warehouse_api_startup")
    try:
        yield
    finally:
        await dispose()
        await close_rabbitmq()
        logger.info("warehouse_api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ecoLens warehouse",
        version=__version__,
        lifespan=lifespan,
    )

    # CORSMiddleware must be the OUTERMOST middleware (added last --
    # Starlette wraps outside-in in reverse registration order). Same
    # ordering ingestion/data-pipeline's identical `main.py` uses.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=500)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.exception_handler(ApiError)(api_error_handler)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error("unhandled_exception", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500, content={"detail": "internal server error"}
        )

    app.include_router(api_router)

    return app


app = create_app()
