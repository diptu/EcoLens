from __future__ import annotations

import asyncio

import pytest

from app.service.ml import registry as registry_module
from app.service.ml.registry import ModelRegistry

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _no_real_mlflow_calls():
    """This module tests `ModelRegistry.refresh`/`watch` themselves --
    override `conftest.py`'s same-named autouse fixture (which stubs out
    `refresh` entirely so *other* test modules never hit real MLflow)
    with a no-op, so these tests exercise the real methods."""
    yield


class _FakeBundle:
    def __init__(self, version: str):
        self.version = version
        self.run_id = f"run-{version}"


class TestModelRegistryRefresh:
    async def test_swaps_in_a_bundle_when_none_was_loaded(self, monkeypatch):
        async def fake_load_bundle(model_name, stage="Production"):
            return _FakeBundle("1")

        monkeypatch.setattr(registry_module, "load_bundle", fake_load_bundle)
        registry = ModelRegistry("lstm_demand")

        swapped = await registry.refresh()

        assert swapped is True
        assert registry.bundle.version == "1"

    async def test_does_not_swap_when_version_is_unchanged(self, monkeypatch):
        call_count = {"n": 0}

        async def fake_load_bundle(model_name, stage="Production"):
            call_count["n"] += 1
            return _FakeBundle("1")

        monkeypatch.setattr(registry_module, "load_bundle", fake_load_bundle)
        registry = ModelRegistry("lstm_demand")
        await registry.refresh()
        first_bundle = registry.bundle

        swapped = await registry.refresh()

        assert swapped is False
        assert (
            registry.bundle is first_bundle
        )  # same object -- no needless reconstruction
        assert call_count["n"] == 2  # still re-checked MLflow both times

    async def test_swaps_when_a_newer_version_appears(self, monkeypatch):
        versions = iter(["1", "2"])

        async def fake_load_bundle(model_name, stage="Production"):
            return _FakeBundle(next(versions))

        monkeypatch.setattr(registry_module, "load_bundle", fake_load_bundle)
        registry = ModelRegistry("lstm_demand")
        await registry.refresh()

        swapped = await registry.refresh()

        assert swapped is True
        assert registry.bundle.version == "2"

    async def test_returns_false_and_keeps_existing_bundle_when_nothing_is_registered(
        self, monkeypatch
    ):
        async def fake_load_bundle(model_name, stage="Production"):
            return None

        monkeypatch.setattr(registry_module, "load_bundle", fake_load_bundle)
        registry = ModelRegistry("lstm_demand")

        swapped = await registry.refresh()

        assert swapped is False
        assert registry.bundle is None


class TestModelRegistryWatch:
    async def test_a_failed_refresh_does_not_crash_the_watch_loop(self, monkeypatch):
        call_count = {"n": 0}

        async def flaky_refresh(self):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("mlflow unreachable")
            return False

        monkeypatch.setattr(ModelRegistry, "refresh", flaky_refresh)
        registry = ModelRegistry("lstm_demand")

        task = asyncio.create_task(registry.watch(interval_seconds=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert call_count["n"] >= 2  # survived the first failure and kept polling
