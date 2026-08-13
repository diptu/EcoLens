from __future__ import annotations

from app.core.middleware import CACHE_CONTROL_VALUE


def test_cacheable_get_route_gets_the_header(client):
    response = client.get("/v1/regions")

    assert response.status_code == 200
    assert response.headers["cache-control"] == CACHE_CONTROL_VALUE


def test_healthz_is_excluded(client):
    response = client.get("/v1/healthz")

    assert response.status_code == 200
    assert "cache-control" not in response.headers


def test_readyz_is_excluded_even_though_it_starts_with_v1(client):
    from app.main import app
    from app.api.v1.deps import get_db, get_model_registry, get_redis_client

    class _OkSession:
        async def execute(self, query, params=None):
            return None

    class _OkRedis:
        async def ping(self):
            return True

    class _FakeRegistry:
        bundle = object()

    app.dependency_overrides[get_db] = lambda: _OkSession()
    app.dependency_overrides[get_redis_client] = lambda: _OkRedis()
    app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry()
    try:
        response = client.get("/v1/readyz")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "cache-control" not in response.headers


def test_a_404_is_not_cached(client):
    from app.main import app
    from app.api.v1.deps import get_db, get_redis_client

    class _FakeSession:
        async def execute(self, query, params=None):
            class _Result:
                def mappings(self):
                    return self

                def first(self):
                    return None

            return _Result()

    class _FakeRedis:
        async def get(self, key):
            return None

        async def set(self, key, value, ex=None):
            return None

    app.dependency_overrides[get_db] = lambda: _FakeSession()
    app.dependency_overrides[get_redis_client] = lambda: _FakeRedis()
    try:
        response = client.get("/v1/emissions?region=DOES-NOT-EXIST")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert "cache-control" not in response.headers
