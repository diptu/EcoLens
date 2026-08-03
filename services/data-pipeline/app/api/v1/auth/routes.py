"""`POST /v1/auth/token` — this service's own real token issuer
(`TODO.md`'s IAM section item 1). The one endpoint in this router that's
deliberately unauthenticated (obviously — it's how you get a token in
the first place); rate-limited like everything else once `Settings.
rate_limit_*` applies (`app.core.ratelimit`), which matters more here than
anywhere else in the API (a bare username/password endpoint is exactly
what brute-forcing targets).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_db, get_redis_client
from app.core.errors import ApiError
from app.schemas.auth import TokenRequest, TokenResponse
from app.service.auth import authenticate, issue_token
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.ratelimit import TokenBucketLimiter

log = get_logger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def issue_token_endpoint(
    request: Request,
    body: TokenRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_app_settings),
) -> TokenResponse:
    # No `Principal` exists yet at this point (that's the whole purpose
    # of this endpoint), so `security._enforce_rate_limit`'s per-`sub`
    # bucket doesn't apply here -- keyed by client IP instead, and
    # deliberately stricter (`rate_limit_login_attempts_per_minute`,
    # default 10 vs. the general API's 60) since this is exactly the
    # endpoint credential-stuffing/brute-force targets. Same fail-open
    # behavior on a Redis error as the general limiter.
    client_ip = request.client.host if request.client else "unknown"
    login_limiter = TokenBucketLimiter(
        redis, capacity=settings.rate_limit_login_attempts_per_minute
    )
    try:
        result = await login_limiter.check(f"login:{client_ip}")
    except Exception as exc:
        log.warning(
            "auth.ratelimit_check_failed_open", client_ip=client_ip, error=str(exc)
        )
    else:
        if not result.allowed:
            raise ApiError(
                429,
                "rate_limited",
                f"Too many login attempts — retry in {result.retry_after_seconds:.1f}s",
            )

    user = await authenticate(db, body.username, body.password)
    if user is None:
        log.info("auth.login_failed", username=body.username, client_ip=client_ip)
        raise ApiError(401, "unauthorized", "Invalid username or password")

    token, expires_in = issue_token(user, settings)
    log.info("auth.login_success", username=user.username, role=user.role)
    return TokenResponse(access_token=token, expires_in=expires_in, role=user.role)
