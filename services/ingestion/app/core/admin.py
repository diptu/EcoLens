"""Admin-token gate for state-changing routes the public dashboard never
calls (data-source edits, raw `/v1/ingest/*` triggers, feature rebuild,
anomaly status edits) -- same module as forecast-api's
`app/core/security.py` (cross-service duplication, this codebase's
convention). The dashboard's own triggers (`.../run`, `.../backfill`)
stay public: they're single-flight (409 while running) and backfill
ranges are already capped at 90 days by the service layer.

Fails closed: with `ADMIN_API_TOKEN` unset, gated routes answer 503.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, Header

from app.api.v1.deps import get_app_settings
from app.core.config import Settings
from app.core.errors import ApiError


def _presented_token(authorization: str | None, x_admin_token: str | None) -> str | None:
    if x_admin_token:
        return x_admin_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def is_admin(
    settings: Settings,
    authorization: str | None,
    x_admin_token: str | None,
) -> bool:
    expected = settings.admin_api_token
    presented = _presented_token(authorization, x_admin_token)
    if not expected or not presented:
        return False
    return hmac.compare_digest(presented.encode(), expected.encode())


async def require_admin(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    settings: Settings = Depends(get_app_settings),
) -> None:
    if not settings.admin_api_token:
        raise ApiError(
            503, "admin_disabled", "Admin routes are disabled: ADMIN_API_TOKEN is not configured"
        )
    if not is_admin(settings, authorization, x_admin_token):
        raise ApiError(401, "unauthorized", "A valid admin token is required for this route")

