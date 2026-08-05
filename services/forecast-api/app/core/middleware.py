"""Edge/CDN cache headers for read-only carbon-analytics endpoints.

TODO.md's "Response Caching & Edge Delivery" — distinct from the
per-endpoint Redis caching each route in `api/v1/*/routes.py` already
does (that avoids recomputing/re-querying on this *service*; this header
lets Vercel/a CDN in front of it skip the round-trip entirely). Applied
via middleware rather than a `response.headers[...] = ...` line in every
route handler so new read endpoints under an already-cacheable prefix
inherit it for free, and so the header value stays defined in exactly one
place.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CACHE_CONTROL_VALUE = "public, s-maxage=300, stale-while-revalidate=60"

# Read-only market/carbon-analytics data — safe for a shared CDN cache to
# serve slightly stale (bounded by `s-maxage=300`, matching this data's
# real update cadence: a 5-minute cron/dbt pipeline run). Deliberately
# excludes `/v1/model*` (operators need current registry/serving state,
# not a CDN-cached snapshot, when deciding whether to promote),
# `/v1/healthz`/`/v1/readyz` (liveness/readiness probes must never be
# cached), and `/v1/stream/*` (a long-lived SSE connection, not a
# cacheable response at all). `/v1/footprint` is POST-only already, so a
# GET-only check below excludes it without needing to list it here.
_CACHEABLE_PREFIXES = (
    "/v1/forecast",
    "/v1/emissions",
    "/v1/demand",
    "/v1/generation-mix",
    "/v1/regions",
)


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if (
            request.method == "GET"
            and response.status_code == 200
            and "cache-control" not in response.headers
            and request.url.path.startswith(_CACHEABLE_PREFIXES)
        ):
            response.headers["Cache-Control"] = CACHE_CONTROL_VALUE
        return response
