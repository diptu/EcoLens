from app.api.v1 import deps
from app.api.v1.health import routes as health_routes


class _FakeDb:
    async def execute(self, query, params=None):
        return None


class _FakeConnection:
    is_closed = False


def test_healthz_never_touches_a_dependency(client):
    response = client.get("/v1/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_ready_when_everything_is_healthy(client, monkeypatch):
    async def fake_get_db():
        yield _FakeDb()

    async def fake_get_connection():
        return _FakeConnection()

    client.app.dependency_overrides[deps.get_db] = fake_get_db
    client.app.dependency_overrides[deps.get_log_db] = fake_get_db
    monkeypatch.setattr(health_routes, "get_rabbitmq_connection", fake_get_connection)

    response = client.get("/v1/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    names = {c["name"] for c in body["components"]}
    assert names == {"postgres", "postgres_log", "rabbitmq"}
    assert all(c["healthy"] for c in body["components"])

    client.app.dependency_overrides.clear()


def test_readyz_reports_not_ready_when_rabbitmq_is_down(client, monkeypatch):
    async def fake_get_db():
        yield _FakeDb()

    async def fake_get_connection():
        raise ConnectionError("no route to broker")

    client.app.dependency_overrides[deps.get_db] = fake_get_db
    client.app.dependency_overrides[deps.get_log_db] = fake_get_db
    monkeypatch.setattr(health_routes, "get_rabbitmq_connection", fake_get_connection)

    response = client.get("/v1/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    rabbitmq_component = next(c for c in body["components"] if c["name"] == "rabbitmq")
    assert rabbitmq_component["healthy"] is False

    client.app.dependency_overrides.clear()


def test_metrics_endpoint_returns_prometheus_text(client):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert b"ecolens_warehouse" in response.content


def test_metrics_endpoint_identifies_this_service_via_build_info(client):
    from app import __version__

    response = client.get("/metrics")

    assert (
        f'ecolens_build_info{{service="warehouse",version="{__version__}"}} 1.0'
        in response.text
    )
