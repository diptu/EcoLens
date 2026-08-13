"""Standard error envelope — same shape as `data-pipeline`'s
`app.core.errors` (`API_SPECEFICATIONS.md`'s § Conventions), so a
client hitting either service's JSON API sees one consistent error
shape. No request-id middleware here (yet) — `request_id` is always
`null` until `main.py` grows one; tracked as a gap, not silently
omitted from the envelope shape."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings


def cors_allow_origin(request: Request) -> str | None:
    """Responses built by `@app.exception_handler(...)`-registered handlers
    (this module's `api_error_handler`, and `main.py`'s catch-all) don't
    pass back through `CORSMiddleware` in this FastAPI/Starlette version —
    confirmed by comparing headers on a normal 200/503 response (has
    `access-control-allow-origin`) against an exception-handler-produced
    500 (didn't, before this fix). A browser `fetch()` against a
    CORS-header-less response reports it as an opaque "Failed to fetch",
    not the real status/body — so every exception handler sets this
    itself rather than relying on the middleware to catch it on the way
    out. Mirrors `CORSMiddleware`'s own decision: `"*"` if the configured
    allow-list is wildcard, otherwise echo the request's `Origin` back
    only if it's actually in that allow-list, otherwise omit the header
    (same as a real disallowed-origin CORS response would)."""
    allowed = get_settings().api_cors_origins
    if "*" in allowed:
        return "*"
    origin = request.headers.get("origin")
    return origin if origin and origin in allowed else None


class ApiError(Exception):
    def __init__(
        self, status_code: int, code: str, message: str, field: str | None = None
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field
        super().__init__(message)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    response = JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "field": exc.field,
                "request_id": None,
            }
        },
    )
    allow_origin = cors_allow_origin(request)
    if allow_origin:
        response.headers["Access-Control-Allow-Origin"] = allow_origin
    return response
