from __future__ import annotations

import asyncio

import pytest

from app.service.pipeline import dbt_build_watch

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _stop_after(n: int):
    """Fake `asyncio.sleep` that raises `CancelledError` on the nth call --
    the real `watch_and_build` loop has no other exit, so this is how
    tests stop it deterministically instead of racing a real background
    task."""
    calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) >= n:
            raise asyncio.CancelledError

    return fake_sleep, calls


async def test_calls_run_dbt_build_locked_each_tick_with_expected_args(monkeypatch):
    calls = []

    async def fake_run_dbt_build_locked(
        redis, *, trigger, triggered_by, max_wait_seconds
    ):
        calls.append((trigger, triggered_by, max_wait_seconds))

    fake_sleep, sleep_calls = _stop_after(3)
    monkeypatch.setattr(
        dbt_build_watch, "run_dbt_build_locked", fake_run_dbt_build_locked
    )
    monkeypatch.setattr(dbt_build_watch.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await dbt_build_watch.watch_and_build(redis=object(), interval_seconds=10)

    assert calls == [("periodic_watch", "scheduler", 0)] * 3
    assert sleep_calls == [10, 10, 10]


async def test_a_lock_in_progress_is_swallowed_not_raised(monkeypatch):
    async def fake_run_dbt_build_locked(redis, **kwargs):
        raise dbt_build_watch.DbtBuildLockTimeout("another build is still running")

    fake_sleep, sleep_calls = _stop_after(1)
    monkeypatch.setattr(
        dbt_build_watch, "run_dbt_build_locked", fake_run_dbt_build_locked
    )
    monkeypatch.setattr(dbt_build_watch.asyncio, "sleep", fake_sleep)

    # Must not raise DbtBuildLockTimeout -- the loop should reach `sleep`
    # (only CancelledError, injected by the fake sleep, should propagate).
    with pytest.raises(asyncio.CancelledError):
        await dbt_build_watch.watch_and_build(redis=object(), interval_seconds=5)

    assert sleep_calls == [5]


async def test_an_unexpected_exception_is_swallowed_not_raised(monkeypatch):
    async def fake_run_dbt_build_locked(redis, **kwargs):
        raise RuntimeError("db unreachable")

    fake_sleep, sleep_calls = _stop_after(1)
    monkeypatch.setattr(
        dbt_build_watch, "run_dbt_build_locked", fake_run_dbt_build_locked
    )
    monkeypatch.setattr(dbt_build_watch.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await dbt_build_watch.watch_and_build(redis=object(), interval_seconds=5)

    assert sleep_calls == [5]
