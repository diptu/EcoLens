import pytest
from starlette.requests import Request

from app.core.errors import ApiError, api_error_handler

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "headers": raw_headers,
        "method": "GET",
        "path": "/",
    }
    return Request(scope)


def test_api_error_carries_status_code_and_fields():
    exc = ApiError(404, "not_found", "no such source", field="id")

    assert exc.status_code == 404
    assert exc.code == "not_found"
    assert exc.message == "no such source"
    assert exc.field == "id"
    assert str(exc) == "no such source"


async def test_api_error_handler_builds_the_error_envelope():
    exc = ApiError(409, "already_running", "a run is already in progress")

    response = await api_error_handler(_request(), exc)

    assert response.status_code == 409
    import json

    body = json.loads(response.body)
    assert body["error"]["code"] == "already_running"
    assert body["error"]["message"] == "a run is already in progress"
    assert body["error"]["field"] is None


async def test_api_error_handler_falls_back_to_the_request_id_header():
    exc = ApiError(500, "internal", "boom")

    response = await api_error_handler(_request({"X-Request-ID": "req-123"}), exc)

    import json

    body = json.loads(response.body)
    assert body["error"]["request_id"] == "req-123"
