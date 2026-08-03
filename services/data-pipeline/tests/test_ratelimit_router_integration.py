"""Router-level 429 wiring: `app.core.security.get_current_principal`
(general per-`sub` limit) and `POST /v1/auth/token` (per-IP login limit)
both call into `app.core.ratelimit.TokenBucketLimiter`, which needs a real
`redis.eval` -- most of this suite's `FakeRedis` fixtures predate rate
limiting and don't implement it (deliberately: `security._enforce_rate_limit`
fails *open* against those, see its own docstring). This file's `FakeRedis`
*does* implement `eval`, faithfully enough to prove the 429 path itself
actually fires when the limiter says no -- real enforcement math is
`test_ratelimit.py`'s job (against real Redis), this is just "does the
wiring work end to end."
"""

from __future__ import annotations

import jwt

from app.main import app
from app.api.v1.deps import get_app_settings, get_db, get_redis_client
from app.service.auth import hash_password
from app.core.config import get_settings
from app.service.datasources import service as datasources_service
from app.service.pipeline.circuit_breaker import CircuitState


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, user_row=None):
        self.user_row = user_row

    async def execute(self, query, params=None):
        sql = str(query)
        if sql.strip().startswith("SELECT"):
            return _FakeResult(self.user_row)
        if sql.strip().startswith("UPDATE"):
            return _FakeResult(None)
        raise AssertionError(f"unexpected query: {sql}")


class _EmptyResultSession:
    """Enough of a DB session for `GET /v1/data-sources` to complete
    normally (200) instead of raising -- these tests only care whether
    the rate limiter's *dependency-level* 429 fires before the endpoint
    body/DB ever gets touched, not what data comes back."""

    class _Result:
        def mappings(self):
            return self

        def all(self):
            return []

    async def execute(self, query, params=None):
        return self._Result()


class _FakeBreaker:
    """`GET /v1/data-sources` reads circuit-breaker state via
    `datasources.service.get_breaker`, which is *not* the FastAPI-injected
    `get_redis_client` this file overrides -- it's its own module-level
    `@lru_cache`d real Redis client (`cache/redis_client.py`'s own
    docstring: "The circuit-breaker reads use a separate Redis client").
    Faked here the same way `test_datasources_router.py`'s `FakeBreaker`
    does, so these rate-limit-focused tests don't need a real Redis
    reachable just to answer "is the breaker open"."""

    @property
    def state(self):
        async def _get():
            return CircuitState.CLOSED

        return _get()


def _fake_get_breaker(name: str) -> _FakeBreaker:
    return _FakeBreaker()


class _FakeRedisWithBucket:
    """A minimal in-Python re-implementation of the Lua token-bucket
    script, exercised via the same `eval(script, numkeys, *args)` call
    shape `TokenBucketLimiter` actually uses -- close enough to prove the
    calling code's wiring, not a claim that this replaces the real
    Redis-side atomicity tests."""

    def __init__(self):
        self.buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, ts)

    async def eval(self, script, numkeys, key, capacity, refill_rate, now, requested):
        capacity = float(capacity)
        refill_rate = float(refill_rate)
        now = float(now)
        requested = float(requested)

        tokens, last_ts = self.buckets.get(key, (capacity, now))
        elapsed = max(0.0, now - last_ts)
        tokens = min(capacity, tokens + elapsed * refill_rate)

        allowed = 0
        if tokens >= requested:
            tokens -= requested
            allowed = 1

        self.buckets[key] = (tokens, now)
        return [allowed, str(tokens)]

    # Unrelated methods some shared dependency chains also touch.
    async def get(self, key):
        return None

    async def set(self, key, value, ex=None):
        return True


def _token(role: str, sub: str) -> str:
    settings = get_settings()
    return jwt.encode(
        {"sub": sub, "role": role},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _settings_with_limit(**overrides):
    """A distinct `Settings` instance (not the process-wide `lru_cache`d
    one) so each test's limit override is isolated -- overridden via
    `get_app_settings`'s dependency, not global monkeypatching."""
    base = get_settings()
    return base.model_copy(update=overrides)


class TestGeneralApiRateLimit:
    def test_requests_within_the_limit_succeed(self, client, monkeypatch):
        monkeypatch.setattr(datasources_service, "get_breaker", _fake_get_breaker)
        redis = _FakeRedisWithBucket()
        app.dependency_overrides[get_redis_client] = lambda: redis
        app.dependency_overrides[get_db] = lambda: _EmptyResultSession()
        app.dependency_overrides[get_app_settings] = lambda: _settings_with_limit(
            rate_limit_requests_per_minute=3
        )
        headers = {"Authorization": f"Bearer {_token('admin', 'ratelimit-user-a')}"}
        try:
            responses = [
                client.get("/v1/data-sources", headers=headers) for _ in range(3)
            ]
        finally:
            app.dependency_overrides.clear()

        # `get_db` is faked (`_EmptyResultSession`) so this only exercises
        # the rate-limiter's dependency-level 429 -- not a real DB/schema.
        assert all(r.status_code != 429 for r in responses)

    def test_exceeding_the_limit_returns_429(self, client, monkeypatch):
        monkeypatch.setattr(datasources_service, "get_breaker", _fake_get_breaker)
        redis = _FakeRedisWithBucket()
        app.dependency_overrides[get_redis_client] = lambda: redis
        app.dependency_overrides[get_db] = lambda: _EmptyResultSession()
        app.dependency_overrides[get_app_settings] = lambda: _settings_with_limit(
            rate_limit_requests_per_minute=2
        )
        headers = {"Authorization": f"Bearer {_token('admin', 'ratelimit-user-b')}"}
        try:
            responses = [
                client.get("/v1/data-sources", headers=headers) for _ in range(3)
            ]
        finally:
            app.dependency_overrides.clear()

        assert responses[2].status_code == 429
        assert responses[2].json()["error"]["code"] == "rate_limited"

    def test_different_callers_have_independent_limits(self, client, monkeypatch):
        monkeypatch.setattr(datasources_service, "get_breaker", _fake_get_breaker)
        redis = _FakeRedisWithBucket()
        app.dependency_overrides[get_redis_client] = lambda: redis
        app.dependency_overrides[get_db] = lambda: _EmptyResultSession()
        app.dependency_overrides[get_app_settings] = lambda: _settings_with_limit(
            rate_limit_requests_per_minute=1
        )
        try:
            client.get(
                "/v1/data-sources",
                headers={"Authorization": f"Bearer {_token('admin', 'caller-x')}"},
            )
            response = client.get(
                "/v1/data-sources",
                headers={"Authorization": f"Bearer {_token('admin', 'caller-y')}"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code != 429


class TestLoginRateLimit:
    def test_exceeding_login_attempts_returns_429(self, client):
        redis = _FakeRedisWithBucket()
        row = {
            "id": "user-1",
            "username": "diptu",
            "password_hash": hash_password("hunter2"),
            "role": "admin",
            "is_active": True,
        }
        app.dependency_overrides[get_db] = lambda: _FakeSession(row)
        app.dependency_overrides[get_redis_client] = lambda: redis
        app.dependency_overrides[get_app_settings] = lambda: _settings_with_limit(
            rate_limit_login_attempts_per_minute=2
        )
        try:
            responses = [
                client.post(
                    "/v1/auth/token", json={"username": "diptu", "password": "wrong"}
                )
                for _ in range(3)
            ]
        finally:
            app.dependency_overrides.clear()

        assert [r.status_code for r in responses[:2]] == [401, 401]
        assert responses[2].status_code == 429
        assert responses[2].json()["error"]["code"] == "rate_limited"
