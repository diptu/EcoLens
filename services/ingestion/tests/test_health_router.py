import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.deps import get_db, get_log_db, get_redis_client
from app.core.config import get_settings
from app.main import app, create_app


class OkSession:
    async def execute(self, *args, **kwargs):
        return None


class FailingSession:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("db down")


class OkRedis:
    async def ping(self):
        return True


class FailingRedis:
    async def ping(self):
        raise RuntimeError("redis down")


class FakeConnection:
    def __init__(self, is_closed: bool):
        self.is_closed = is_closed


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_healthz_returns_ok(client):
    response = client.get("/v1/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_returns_prometheus_text(client):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "ecolens_" in response.text


def test_request_id_is_generated_when_absent(client):
    response = client.get("/v1/healthz")

    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0


def test_request_id_is_echoed_when_supplied(client):
    response = client.get("/v1/healthz", headers={"X-Request-ID": "abc-123"})

    assert response.headers["x-request-id"] == "abc-123"


async def _ok_rabbitmq_connection():
    return FakeConnection(is_closed=False)


async def _closed_rabbitmq_connection():
    return FakeConnection(is_closed=True)


async def _failing_rabbitmq_connection():
    raise RuntimeError("rabbitmq down")


def test_readyz_returns_200_when_all_components_healthy(client, monkeypatch):
    app.dependency_overrides[get_db] = lambda: OkSession()
    app.dependency_overrides[get_log_db] = lambda: OkSession()
    app.dependency_overrides[get_redis_client] = lambda: OkRedis()
    monkeypatch.setattr(
        "app.api.v1.health.routes.get_rabbitmq_connection",
        _ok_rabbitmq_connection,
    )

    response = client.get("/v1/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert all(c["healthy"] for c in body["components"])


def test_readyz_returns_503_when_postgres_is_unhealthy(client, monkeypatch):
    app.dependency_overrides[get_db] = lambda: FailingSession()
    app.dependency_overrides[get_log_db] = lambda: OkSession()
    app.dependency_overrides[get_redis_client] = lambda: OkRedis()
    monkeypatch.setattr(
        "app.api.v1.health.routes.get_rabbitmq_connection",
        _ok_rabbitmq_connection,
    )

    response = client.get("/v1/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    postgres = next(c for c in body["components"] if c["name"] == "postgres")
    assert postgres["healthy"] is False
    assert "db down" in postgres["detail"]


def test_readyz_returns_503_when_log_postgres_is_unhealthy(client, monkeypatch):
    """The separate logging database (`LOG_DB_URL`, 2026-08-12) is its
    own real dependency now -- it going down must be visibly distinct
    from the primary database's own health, not silently masked by it
    (or vice versa)."""
    app.dependency_overrides[get_db] = lambda: OkSession()
    app.dependency_overrides[get_log_db] = lambda: FailingSession()
    app.dependency_overrides[get_redis_client] = lambda: OkRedis()
    monkeypatch.setattr(
        "app.api.v1.health.routes.get_rabbitmq_connection",
        _ok_rabbitmq_connection,
    )

    response = client.get("/v1/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    postgres = next(c for c in body["components"] if c["name"] == "postgres")
    assert postgres["healthy"] is True
    postgres_log = next(c for c in body["components"] if c["name"] == "postgres_log")
    assert postgres_log["healthy"] is False
    assert "db down" in postgres_log["detail"]


def test_readyz_returns_503_when_redis_is_unhealthy(client, monkeypatch):
    app.dependency_overrides[get_db] = lambda: OkSession()
    app.dependency_overrides[get_log_db] = lambda: OkSession()
    app.dependency_overrides[get_redis_client] = lambda: FailingRedis()
    monkeypatch.setattr(
        "app.api.v1.health.routes.get_rabbitmq_connection",
        _ok_rabbitmq_connection,
    )

    response = client.get("/v1/readyz")

    assert response.status_code == 503
    redis = next(c for c in response.json()["components"] if c["name"] == "redis")
    assert redis["healthy"] is False
    assert "redis down" in redis["detail"]


def test_readyz_marks_rabbitmq_unhealthy_when_connection_is_closed(client, monkeypatch):
    app.dependency_overrides[get_db] = lambda: OkSession()
    app.dependency_overrides[get_log_db] = lambda: OkSession()
    app.dependency_overrides[get_redis_client] = lambda: OkRedis()
    monkeypatch.setattr(
        "app.api.v1.health.routes.get_rabbitmq_connection",
        _closed_rabbitmq_connection,
    )

    response = client.get("/v1/readyz")

    assert response.status_code == 503
    rabbitmq = next(c for c in response.json()["components"] if c["name"] == "rabbitmq")
    assert rabbitmq["healthy"] is False
    assert "closed" in rabbitmq["detail"]


def test_readyz_marks_rabbitmq_unhealthy_on_connection_error(client, monkeypatch):
    app.dependency_overrides[get_db] = lambda: OkSession()
    app.dependency_overrides[get_log_db] = lambda: OkSession()
    app.dependency_overrides[get_redis_client] = lambda: OkRedis()
    monkeypatch.setattr(
        "app.api.v1.health.routes.get_rabbitmq_connection",
        _failing_rabbitmq_connection,
    )

    response = client.get("/v1/readyz")

    assert response.status_code == 503
    rabbitmq = next(c for c in response.json()["components"] if c["name"] == "rabbitmq")
    assert rabbitmq["healthy"] is False
    assert "rabbitmq down" in rabbitmq["detail"]


def test_unhandled_exception_returns_500_json():
    isolated_app = create_app()

    @isolated_app.get("/boom")
    async def boom() -> None:
        raise ValueError("kaboom")

    with TestClient(isolated_app, raise_server_exceptions=False) as c:
        response = c.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}


def test_create_app_uses_cors_origins_from_settings():
    get_settings.cache_clear()
    built = create_app()

    assert isinstance(built, FastAPI)
    cors_middleware = next(
        m for m in built.user_middleware if m.cls.__name__ == "CORSMiddleware"
    )
    assert cors_middleware.kwargs["allow_origins"] == get_settings().api_cors_origins
