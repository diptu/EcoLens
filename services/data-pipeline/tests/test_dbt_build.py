from __future__ import annotations

import uuid

import pytest

from app.service.pipeline import dbt_build

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


@pytest.fixture(autouse=True)
def fake_build_log(monkeypatch):
    """`run_dbt_build_locked` now writes `meta._dbt_build_log` rows
    (TODO.md's backfill section Follow-up item) -- fake the writes for
    every test in this module so none of them need a real Postgres.
    Tests that care about what got logged request this fixture
    explicitly to inspect `.started`/`.finished`."""
    calls = {"started": [], "finished": []}

    async def fake_start(**kwargs):
        calls["started"].append(kwargs)
        return uuid.uuid4()

    async def fake_finish(log_id, **kwargs):
        calls["finished"].append({"log_id": log_id, **kwargs})

    monkeypatch.setattr(dbt_build, "log_dbt_build_start", fake_start)
    monkeypatch.setattr(dbt_build, "log_dbt_build_finish", fake_finish)
    return calls


async def test_runs_dbt_build_and_releases_the_lock(monkeypatch, fake_build_log):
    calls = []

    def fake_run_dbt(subcommand, project_dir, target, *args, **kwargs):
        calls.append((subcommand, project_dir, target))
        return 0

    monkeypatch.setattr(dbt_build, "run_dbt", fake_run_dbt)
    redis = FakeRedis()

    exit_code = await dbt_build.run_dbt_build_locked(
        redis, trigger="backfill_auto", triggered_by="test"
    )

    assert exit_code == 0
    assert calls == [
        (
            "build",
            dbt_build.get_settings().dbt_project_dir,
            dbt_build.get_settings().dbt_target,
        )
    ]
    assert dbt_build.DBT_BUILD_LOCK_KEY not in redis.store  # released
    assert fake_build_log["started"] == [
        {
            "subcommand": "build",
            "target": dbt_build.get_settings().dbt_target,
            "trigger": "backfill_auto",
            "triggered_by": "test",
        }
    ]
    assert fake_build_log["finished"][0]["status"] == "success"
    assert fake_build_log["finished"][0]["exit_code"] == 0


async def test_returns_the_real_nonzero_exit_code_on_failure(
    monkeypatch, fake_build_log
):
    monkeypatch.setattr(dbt_build, "run_dbt", lambda *a, **k: 1)
    redis = FakeRedis()

    exit_code = await dbt_build.run_dbt_build_locked(
        redis, trigger="backfill_auto", triggered_by="test"
    )

    assert exit_code == 1
    assert dbt_build.DBT_BUILD_LOCK_KEY not in redis.store  # still released
    assert fake_build_log["finished"][0]["status"] == "failed"
    assert fake_build_log["finished"][0]["exit_code"] == 1


async def test_fails_fast_when_max_wait_seconds_is_zero_and_lock_is_held(
    monkeypatch, fake_build_log
):
    called = False

    def fake_run_dbt(*a, **k):
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(dbt_build, "run_dbt", fake_run_dbt)
    redis = FakeRedis()
    redis.store[dbt_build.DBT_BUILD_LOCK_KEY] = "someone-elses-token"

    with pytest.raises(dbt_build.DbtBuildLockTimeout):
        await dbt_build.run_dbt_build_locked(
            redis, trigger="dashboard_manual", triggered_by="test", max_wait_seconds=0
        )

    assert called is False  # never even attempted the build
    # The lock stays exactly as the other holder left it -- we never
    # acquired it, so we must never touch it.
    assert redis.store[dbt_build.DBT_BUILD_LOCK_KEY] == "someone-elses-token"
    # No build attempt happened -- nothing to log.
    assert fake_build_log["started"] == []
    assert fake_build_log["finished"] == []


async def test_waits_for_the_lock_to_free_then_proceeds(monkeypatch, fake_build_log):
    monkeypatch.setattr(dbt_build, "run_dbt", lambda *a, **k: 0)
    monkeypatch.setattr(dbt_build, "DBT_BUILD_LOCK_POLL_SECONDS", 0)
    redis = FakeRedis()
    redis.store[dbt_build.DBT_BUILD_LOCK_KEY] = "in-flight-elsewhere"

    async def release_soon():
        del redis.store[dbt_build.DBT_BUILD_LOCK_KEY]

    import asyncio

    release_task = asyncio.ensure_future(release_soon())
    exit_code = await dbt_build.run_dbt_build_locked(
        redis, trigger="backfill_auto", triggered_by="test", max_wait_seconds=5
    )
    await release_task

    assert exit_code == 0
