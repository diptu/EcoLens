from __future__ import annotations

import httpx
import pytest

from app.service.pipeline.http_retry import fetch_with_retry

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/x")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError(f"{code}", request=request, response=response)


async def test_succeeds_on_first_attempt_without_sleeping(monkeypatch):
    calls = 0
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("app.service.pipeline.http_retry.asyncio.sleep", fake_sleep)

    async def fn():
        nonlocal calls
        calls += 1
        return "ok"

    result = await fetch_with_retry(fn, log_event="test.retry")

    assert result == "ok"
    assert calls == 1
    assert slept == []


async def test_retries_on_transport_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(
        "app.service.pipeline.http_retry.asyncio.sleep", _make_fake_sleep()
    )
    attempts = []

    async def fn():
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("connection reset")
        return "recovered"

    result = await fetch_with_retry(fn, log_event="test.retry", max_attempts=3)

    assert result == "recovered"
    assert len(attempts) == 3


async def test_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr(
        "app.service.pipeline.http_retry.asyncio.sleep", _make_fake_sleep()
    )
    attempts = []

    async def fn():
        attempts.append(1)
        if len(attempts) < 2:
            raise _status_error(503)
        return "recovered"

    result = await fetch_with_retry(fn, log_event="test.retry", max_attempts=3)

    assert result == "recovered"
    assert len(attempts) == 2


async def test_does_not_retry_a_4xx(monkeypatch):
    monkeypatch.setattr(
        "app.service.pipeline.http_retry.asyncio.sleep", _make_fake_sleep()
    )
    attempts = []

    async def fn():
        attempts.append(1)
        raise _status_error(404)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await fetch_with_retry(fn, log_event="test.retry", max_attempts=3)

    assert exc_info.value.response.status_code == 404
    assert len(attempts) == 1  # no retry attempted


async def test_raises_the_last_error_after_exhausting_all_attempts(monkeypatch):
    monkeypatch.setattr(
        "app.service.pipeline.http_retry.asyncio.sleep", _make_fake_sleep()
    )
    attempts = []

    async def fn():
        attempts.append(1)
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(httpx.ConnectTimeout):
        await fetch_with_retry(fn, log_event="test.retry", max_attempts=3)

    assert len(attempts) == 3


def _make_fake_sleep():
    async def _sleep(seconds):
        return None

    return _sleep
