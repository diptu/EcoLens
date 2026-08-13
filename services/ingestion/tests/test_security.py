"""Direct, route-independent tests for `app.core.security`.

No route in this service currently wires `require_roles`/
`get_current_principal` in ("no auth required for now" — see `app.
api.v1.datasources.routes`'s own module docstring for why), so this
exercises the dependency functions directly rather than through a
`TestClient` request, the same way `test_ratelimit.py` tests
`TokenBucketLimiter` standalone. Keeps this real, working, ported module
validated and ready to re-wire onto a route later without bit-rotting
unnoticed in the meantime.
"""

from __future__ import annotations

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core import security
from app.core.config import get_settings
from app.core.errors import ApiError

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeRedis:
    """Doesn't implement `eval` -- `_enforce_rate_limit` must fail open
    against this, matching its own docstring."""

    async def get(self, key):
        return None

    async def set(self, key, value, ex=None):
        return True


def _token(sub: str, role: str | None, *, secret: str, algorithm: str = "HS256") -> str:
    payload: dict[str, object] = {"sub": sub}
    if role is not None:
        payload["role"] = role
    return jwt.encode(payload, secret, algorithm=algorithm)


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class TestDecodeBearerToken:
    def test_decodes_a_token_signed_with_the_own_secret(self):
        settings = get_settings()
        token = _token("user-1", "admin", secret=settings.jwt_secret)

        payload = security._decode_bearer_token(token, settings)

        assert payload["sub"] == "user-1"
        assert payload["role"] == "admin"

    def test_falls_back_to_the_iam_secret_when_configured(self):
        settings = get_settings().model_copy(
            update={"iam_jwt_secret": "iam-shared-secret-at-least-32-bytes-long"}
        )
        token = _token(
            "user-2", "analyst", secret="iam-shared-secret-at-least-32-bytes-long"
        )

        payload = security._decode_bearer_token(token, settings)

        assert payload["sub"] == "user-2"

    def test_invalid_token_raises_401(self):
        settings = get_settings()

        with pytest.raises(ApiError) as exc_info:
            security._decode_bearer_token("not-a-real-jwt", settings)

        assert exc_info.value.status_code == 401
        assert exc_info.value.code == "unauthorized"

    def test_token_signed_with_an_unconfigured_secret_is_rejected(self):
        settings = get_settings().model_copy(update={"iam_jwt_secret": None})
        token = _token(
            "user-3", "admin", secret="some-other-secret-at-least-32-bytes-long"
        )

        with pytest.raises(ApiError):
            security._decode_bearer_token(token, settings)


class TestGetCurrentPrincipal:
    async def test_missing_credentials_is_401(self):
        with pytest.raises(ApiError) as exc_info:
            await security.get_current_principal(
                credentials=None, settings=get_settings(), redis=_FakeRedis()
            )

        assert exc_info.value.status_code == 401

    async def test_token_missing_role_claim_is_401(self):
        settings = get_settings()
        token = _token("user-4", None, secret=settings.jwt_secret)

        with pytest.raises(ApiError) as exc_info:
            await security.get_current_principal(
                credentials=_credentials(token), settings=settings, redis=_FakeRedis()
            )

        assert exc_info.value.status_code == 401

    async def test_valid_token_returns_a_principal(self):
        settings = get_settings()
        token = _token("user-5", "analyst", secret=settings.jwt_secret)

        principal = await security.get_current_principal(
            credentials=_credentials(token), settings=settings, redis=_FakeRedis()
        )

        assert principal.sub == "user-5"
        assert principal.role == "analyst"

    async def test_rate_limiter_failing_open_does_not_block_a_valid_token(self):
        """`_FakeRedis` has no `eval` -- `_enforce_rate_limit` must catch
        that and let the request through anyway (fail open), not 500."""
        settings = get_settings()
        token = _token("user-6", "admin", secret=settings.jwt_secret)

        principal = await security.get_current_principal(
            credentials=_credentials(token), settings=settings, redis=_FakeRedis()
        )

        assert principal.sub == "user-6"


class TestRequireRoles:
    async def test_allows_a_role_in_the_list(self):
        principal = security.Principal(sub="user-7", role="admin")
        dependency = security.require_roles("admin", "analyst")

        result = await dependency(principal=principal)

        assert result is principal

    async def test_rejects_a_role_not_in_the_list(self):
        principal = security.Principal(sub="user-8", role="viewer")
        dependency = security.require_roles("admin")

        with pytest.raises(ApiError) as exc_info:
            await dependency(principal=principal)

        assert exc_info.value.status_code == 403
        assert exc_info.value.code == "forbidden"

    def test_roles_constant_covers_admin_and_analyst(self):
        assert security.ROLES == ("admin", "analyst")
