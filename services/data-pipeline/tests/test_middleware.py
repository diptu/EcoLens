from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.middleware import RequestIdMiddleware
from app.core.logging import clear_context


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def ping() -> dict:
        return {"pong": True}

    return app


def test_generates_a_request_id_when_none_supplied():
    clear_context()
    with TestClient(_build_app()) as client:
        response = client.get("/ping")

    assert response.headers["x-request-id"]


def test_echoes_the_supplied_request_id():
    clear_context()
    with TestClient(_build_app()) as client:
        response = client.get("/ping", headers={"X-Request-ID": "fixed-id"})

    assert response.headers["x-request-id"] == "fixed-id"
