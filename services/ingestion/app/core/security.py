"""JWT bearer auth — verification-only, ported from data-pipeline's
identical module (`services/ingestion/TODO.md`'s "implement remaining
API endpoints" follow-up to Phase 1's original trigger-only scope
decision).

Verifies the `Authorization: Bearer <token>` header against `Settings.
jwt_secret`/`jwt_algorithm` **or** `Settings.iam_jwt_secret`/
`iam_jwt_algorithm` — see `_decode_bearer_token`. Either signature is
accepted. Unlike data-pipeline's copy, this service has no `meta.
api_users`/`POST /v1/auth/token` of its own — it never issues tokens,
only verifies ones someone else issued. Two practical ways a caller
gets a valid token here: (1) `jwt_secret` set to the same value as
data-pipeline's own `JWT_SECRET`, so a token that service issued via
its `POST /v1/auth/token` verifies here too (same HS256 shared secret,
two independent verifiers); (2) IAM's own access tokens via `Settings.
iam_jwt_secret` (`None` by default, disabling that bridge entirely) —
same trust-anchor shape data-pipeline's own IAM bridge uses, so the
dashboard's existing IAM session can call admin-gated routes on *either*
service without a second login.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis

from app.api.v1.deps import get_app_settings, get_redis_client
from app.core.errors import ApiError
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.ratelimit import TokenBucketLimiter

log = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)

ROLES = ("admin", "analyst")


@dataclass(frozen=True)
class Principal:
    sub: str
    role: str


async def _enforce_rate_limit(sub: str, redis: Redis, settings: Settings) -> None:
    """429 (spec code `rate_limited`) once `sub` exceeds `Settings.
    rate_limit_requests_per_minute`. Fails *open* (allows the request,
    just logs a warning) if the Redis call itself errors — a rate
    limiter going down is not a reason to take the whole API down with
    it, and this deliberately includes the case where `redis` is a test
    double that doesn't implement `eval` (the vast majority of this
    suite's `FakeRedis` fixtures predate rate limiting and only stub
    `get`/`set`/`delete`) — real enforcement is covered by
    `tests/test_ratelimit.py`'s own dedicated fakes/real-Redis tests
    instead of requiring every other test file to grow an `eval` stub."""
    limiter = TokenBucketLimiter(
        redis, capacity=settings.rate_limit_requests_per_minute
    )
    try:
        result = await limiter.check(sub)
    except Exception as exc:
        log.warning("ratelimit.check_failed_open", sub=sub, error=str(exc))
        return
    if not result.allowed:
        raise ApiError(
            429,
            "rate_limited",
            f"Rate limit exceeded ({result.limit} requests/min) — retry in "
            f"{result.retry_after_seconds:.1f}s",
        )


def _decode_bearer_token(token: str, settings: Settings) -> dict:
    """Tries this service's own secret first (self-issued `meta.api_users`
    tokens, unchanged behavior), then falls back to IAM's secret if one's
    configured (`settings.iam_jwt_secret`) — a token only has to verify
    against *one* of the two trust anchors, not both. Two independent
    secrets rather than switching to a single shared one so each
    issuer's tokens keep working if the other's secret ever rotates."""
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.InvalidTokenError:
        pass

    if settings.iam_jwt_secret:
        try:
            return jwt.decode(
                token, settings.iam_jwt_secret, algorithms=[settings.iam_jwt_algorithm]
            )
        except jwt.InvalidTokenError:
            pass

    raise ApiError(401, "unauthorized", "Invalid or expired token")


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_app_settings),
    redis: Redis = Depends(get_redis_client),
) -> Principal:
    if credentials is None:
        raise ApiError(401, "unauthorized", "Missing bearer token")

    payload = _decode_bearer_token(credentials.credentials, settings)

    sub = payload.get("sub")
    role = payload.get("role")
    if not sub or not role:
        raise ApiError(401, "unauthorized", "Token missing a sub/role claim")

    await _enforce_rate_limit(sub, redis, settings)

    return Principal(sub=sub, role=role)


def require_roles(*roles: str):
    """Dependency factory: 403 (spec code `forbidden`) if the caller's role
    isn't in `roles`. Use `require_roles(*ROLES)` for "any authenticated
    admin or analyst", or `require_roles("admin")` for admin-only routes."""

    async def _dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if principal.role not in roles:
            raise ApiError(
                403,
                "forbidden",
                f"Endpoint requires role: {' or '.join(roles)}",
            )
        return principal

    return _dependency
