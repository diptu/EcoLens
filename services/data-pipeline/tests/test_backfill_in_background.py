"""`run_backfill_in_background`'s new dbt-build trigger (TODO.md's
backfill section: the API-triggered path never refreshed
`raw_marts.*` on its own, unlike `scripts/backfill.py`'s CLI wrapper).
Router-level tests (`test_datasource_actions_router.py`) monkeypatch
this whole function to a no-op, so its actual behavior needs direct
coverage here."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.service.datasources import actions
from app.service.pipeline.dbt_build import DbtBuildLockTimeout

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)


START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 1, 8, tzinfo=UTC)


async def test_runs_one_dbt_build_after_a_successful_backfill(monkeypatch):
    dbt_calls = []

    async def fake_run_backfill(sources, start_date, end_date):
        return {}

    async def fake_run_dbt_build_locked(redis, *, trigger, triggered_by):
        assert trigger == "backfill_auto"
        dbt_calls.append(triggered_by)
        return 0

    monkeypatch.setattr(actions, "run_backfill", fake_run_backfill)
    monkeypatch.setattr(actions, "run_dbt_build_locked", fake_run_dbt_build_locked)
    redis = FakeRedis()
    redis.store["backfill:lock:ds-aemo-nem"] = "bf-1"

    await actions.run_backfill_in_background(
        redis, "ds-aemo-nem", "aemo_nem", START, END
    )

    assert dbt_calls == ["backfill:ds-aemo-nem"]
    assert "backfill:lock:ds-aemo-nem" not in redis.store  # per-source lock released


async def test_skips_dbt_build_when_skip_dbt_is_true(monkeypatch):
    dbt_calls = []

    async def fake_run_backfill(sources, start_date, end_date):
        return {}

    async def fake_run_dbt_build_locked(redis, *, trigger, triggered_by):
        assert trigger == "backfill_auto"
        dbt_calls.append(triggered_by)
        return 0

    monkeypatch.setattr(actions, "run_backfill", fake_run_backfill)
    monkeypatch.setattr(actions, "run_dbt_build_locked", fake_run_dbt_build_locked)
    redis = FakeRedis()

    await actions.run_backfill_in_background(
        redis, "ds-aemo-nem", "aemo_nem", START, END, skip_dbt=True
    )

    assert dbt_calls == []


async def test_skips_dbt_build_when_the_backfill_itself_raises(monkeypatch):
    dbt_calls = []

    async def fake_run_backfill(sources, start_date, end_date):
        raise RuntimeError("db unreachable")

    async def fake_run_dbt_build_locked(redis, *, trigger, triggered_by):
        assert trigger == "backfill_auto"
        dbt_calls.append(triggered_by)
        return 0

    monkeypatch.setattr(actions, "run_backfill", fake_run_backfill)
    monkeypatch.setattr(actions, "run_dbt_build_locked", fake_run_dbt_build_locked)
    redis = FakeRedis()
    redis.store["backfill:lock:ds-aemo-nem"] = "bf-1"

    await actions.run_backfill_in_background(
        redis, "ds-aemo-nem", "aemo_nem", START, END
    )

    assert dbt_calls == []  # no new data landed -- nothing to rebuild
    assert "backfill:lock:ds-aemo-nem" not in redis.store  # still released


async def test_a_dbt_build_lock_timeout_does_not_crash_the_background_task(monkeypatch):
    async def fake_run_backfill(sources, start_date, end_date):
        return {}

    async def fake_run_dbt_build_locked(redis, *, trigger, triggered_by):
        raise DbtBuildLockTimeout("another build is still running")

    monkeypatch.setattr(actions, "run_backfill", fake_run_backfill)
    monkeypatch.setattr(actions, "run_dbt_build_locked", fake_run_dbt_build_locked)
    redis = FakeRedis()

    # Must not raise -- a stuck rebuild is a real, logged gap, not a
    # reason to crash a background task whose backfill already succeeded.
    await actions.run_backfill_in_background(
        redis, "ds-aemo-nem", "aemo_nem", START, END
    )
