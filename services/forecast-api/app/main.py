"""FastAPI application factory for forecast-api.

Served by `uvicorn app.main:app` (`infra/docker/
forecast-api.Dockerfile`, `Makefile`'s `make api` target).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import ApiError, cors_allow_origin, api_error_handler
from app.core.logging import configure_logging, get_logger
from app.core.middleware import CacheControlMiddleware
from app.db.session import dispose, get_engine
from app.service.ml.registry import ModelRegistry

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    get_engine()

    settings = get_settings()
    registry = ModelRegistry(settings.mlflow_registry_model_name)
    app.state.model_registry = registry

    # Loads whatever's in Production *before* accepting traffic (so the
    # very first request doesn't 503 with "model not loaded" just because
    # the poll hadn't run yet), then keeps polling in the background —
    # `service/ml/registry.py`'s "atomic pointer swap" hot-reload. Bounded
    # by a timeout: MLflow's HTTP client retries with backoff on a
    # connection failure rather than failing fast (observed directly while
    # building this -- an unreachable tracking server can stall for well
    # over a minute), and a misconfigured `MLFLOW_TRACKING_URI` shouldn't
    # be able to delay this service from becoming ready to serve
    # `/v1/healthz`/`/v1/regions`/etc. (endpoints that don't need a model
    # at all) by that long. The background `watch_task` below will keep
    # retrying on its own schedule regardless of whether this first
    # attempt timed out.
    try:
        await asyncio.wait_for(registry.refresh(), timeout=10.0)
    except TimeoutError:
        logger.error("startup.initial_model_load_timed_out")
    except Exception as exc:
        logger.error("startup.initial_model_load_failed", error=str(exc))

    watch_task = asyncio.create_task(
        registry.watch(settings.model_reload_interval_seconds)
    )

    logger.info("forecast_api_startup", model_loaded=registry.bundle is not None)
    try:
        yield
    finally:
        watch_task.cancel()
        await dispose()
        logger.info("forecast_api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="ecoLens forecast-api", version=__version__, lifespan=lifespan)

    # Compresses response bodies over the default 500-byte threshold —
    # `GET /v1/forecast`/`/v1/emissions/timeseries` etc. return per-point
    # time-series arrays that are exactly the "large JSON payload" case
    # this helps (TODO.md's Payload Compression item). Added before
    # `CORSMiddleware` so CORS stays outermost (see data-pipeline's
    # `main.py` for why that ordering matters for error responses).
    app.add_middleware(GZipMiddleware, minimum_size=500)
    # Same before-CORS ordering as GZipMiddleware above -- see its comment.
    app.add_middleware(CacheControlMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # See data-pipeline's `main.py` for why this is the decorator form
    # rather than `add_exception_handler(ApiError, api_error_handler)`
    # (which fails mypy on the handler's narrowed `ApiError` param type).
    app.exception_handler(ApiError)(api_error_handler)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error("unhandled_exception", path=request.url.path, error=str(exc))
        response = JSONResponse(
            status_code=500, content={"detail": "internal server error"}
        )
        # See `app.core.errors.cors_allow_origin`'s docstring — responses
        # built here don't pass back through `CORSMiddleware` in this
        # FastAPI/Starlette version, so the header has to be set by hand.
        allow_origin = cors_allow_origin(request)
        if allow_origin:
            response.headers["Access-Control-Allow-Origin"] = allow_origin
        return response

    app.include_router(api_router)

    return app


app = create_app()
