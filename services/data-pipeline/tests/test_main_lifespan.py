from __future__ import annotations

import asyncio

import pytest

import app.main as main_module
from app.core.config import get_settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_lifespan_starts_and_cancels_the_watch_task_by_default(monkeypatch):
    started: list[float] = []

    async def fake_watch_and_build(redis, interval_seconds):
        started.append(interval_seconds)
        await asyncio.Event().wait()  # hangs until the lifespan cancels it

    monkeypatch.setattr(main_module, "watch_and_build", fake_watch_and_build)
    isolated_app = main_module.create_app()

    async with main_module.lifespan(isolated_app):
        await asyncio.sleep(0)  # let the background task actually start
        assert started == [pytest.approx(300.0)]  # Settings' real default

    # Exiting the lifespan must not hang or raise -- the task was
    # cancelled, not left running or awaited to completion.


async def test_lifespan_skips_the_watch_task_when_interval_is_disabled(
    monkeypatch,
):
    started: list[float] = []

    async def fake_watch_and_build(redis, interval_seconds):
        started.append(interval_seconds)
        await asyncio.Event().wait()

    monkeypatch.setattr(main_module, "watch_and_build", fake_watch_and_build)
    monkeypatch.setenv("DBT_AUTO_BUILD_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    isolated_app = main_module.create_app()

    async with main_module.lifespan(isolated_app):
        await asyncio.sleep(0)
        assert started == []
