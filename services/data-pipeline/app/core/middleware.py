"""Request-ID propagation.

Reads `X-Request-ID` off the incoming request (or generates one), binds it
to the structlog context for the lifetime of the request so every log line
emitted while handling it carries the id (ECO-D03), and echoes it back on
the response so callers can correlate.

Also the last line of defense for turning an unhandled exception into a
real HTTP response *before* it can escape this middleware's `call_next()`.
`BaseHTTPMiddleware`-based middlewares (this one) run the downstream ASGI
app in a way that re-raises an exception directly out of `call_next()`
rather than letting it flow through FastAPI's registered
`@app.exception_handler(...)` machinery — confirmed by reproducing a real
`asyncpg.exceptions.InvalidPasswordError` from `GET
/v1/ingestion/public/pipelines` and observing it bypass both the `ApiError`
handler and the catch-all `Exception` handler in `app/main.py` entirely,
unwinding all the way to Starlette's own outermost error handling. Since
that outermost layer sits *outside* every middleware this app adds
(`CORSMiddleware` included, no matter its registration order), a response
built there never gets a CORS header — which a browser `fetch()` reports
as an opaque "Failed to fetch", not the real status/body. Catching here
guarantees `call_next()` always returns a normal `Response` object that
the (now-outermost, see `app/main.py`) `CORSMiddleware` gets a real chance
to process.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_request_id, clear_context, get_logger

REQUEST_ID_HEADER = "X-Request-ID"

logger = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Deferred import: `app.core.errors` imports `REQUEST_ID_HEADER` from
        # this module at load time, so importing it back at module level
        # here would be circular. A local import inside `dispatch` is safe
        # — by request time both modules are already fully initialized.
        from app.core.errors import ApiError, api_error_handler

        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        bind_request_id(request_id)
        try:
            try:
                response = await call_next(request)
            except ApiError as exc:
                response = await api_error_handler(request, exc)
            except Exception as exc:  # noqa: BLE001 - last-resort catch, see module docstring
                logger.error(
                    "unhandled_exception", path=request.url.path, error=str(exc)
                )
                response = JSONResponse(
                    status_code=500, content={"detail": "internal server error"}
                )
        finally:
            clear_context()
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
