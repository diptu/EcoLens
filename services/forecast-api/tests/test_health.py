from __future__ import annotations

from app.main import app
from app.api.v1.deps import get_db, get_model_registry, get_redis_client


class _OkSession:
    async def execute(self, query, params=None):
        return None


class _FailingSession:
    async def execute(self, query, params=None):
        raise RuntimeError("db is down")


class _OkRedis:
    async def ping(self):
        return True


class _FailingRedis:
    async def ping(self):
        raise RuntimeError("redis is down")


class _FakeRegistry:
    def __init__(self, bundle=None):
        self.bundle = bundle


def test_healthz(client):
    response = client.get("/v1/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_returns_prometheus_text(client):
    # No `/v1` prefix -- matches data-pipeline/ingestion/warehouse's
    # existing `/metrics` convention (see app/api/v1/health/routes.py's
    # module docstring).
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "ecolens_" in response.text


def test_metrics_identifies_this_service_via_build_info(client):
    from app import __version__

    response = client.get("/metrics")

    assert (
        f'ecolens_build_info{{service="forecast-api",version="{__version__}"}} 1.0'
        in response.text
    )


class TestReadyz:
    def test_ready_when_everything_is_up(self, client):
        app.dependency_overrides[get_db] = lambda: _OkSession()
        app.dependency_overrides[get_redis_client] = lambda: _OkRedis()
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=object()
        )
        try:
            response = client.get("/v1/readyz")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["ready"] is True
        assert body["database"]["ok"] is True
        assert body["redis"]["ok"] is True
        assert body["model"]["ok"] is True

    def test_not_ready_when_db_is_down(self, client):
        app.dependency_overrides[get_db] = lambda: _FailingSession()
        app.dependency_overrides[get_redis_client] = lambda: _OkRedis()
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=object()
        )
        try:
            response = client.get("/v1/readyz")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["database"]["ok"] is False
        assert "db is down" in body["database"]["detail"]

    def test_not_ready_when_redis_is_down(self, client):
        app.dependency_overrides[get_db] = lambda: _OkSession()
        app.dependency_overrides[get_redis_client] = lambda: _FailingRedis()
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=object()
        )
        try:
            response = client.get("/v1/readyz")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        assert response.json()["redis"]["ok"] is False

    def test_not_ready_when_no_model_loaded(self, client):
        app.dependency_overrides[get_db] = lambda: _OkSession()
        app.dependency_overrides[get_redis_client] = lambda: _OkRedis()
        app.dependency_overrides[get_model_registry] = lambda: _FakeRegistry(
            bundle=None
        )
        try:
            response = client.get("/v1/readyz")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        assert response.json()["model"]["ok"] is False
