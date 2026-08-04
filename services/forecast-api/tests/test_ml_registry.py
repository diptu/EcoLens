from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.service.ml import registry as registry_module
from app.service.ml.registry import (
    ModelRegistry,
    PromotionRejected,
    list_versions,
    promote_version,
)

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


class _FakeVersion:
    def __init__(self, version: str, stage: str, run_id: str, creation_timestamp: int):
        self.version = version
        self.current_stage = stage
        self.run_id = run_id
        self.creation_timestamp = creation_timestamp


class _FakeRunData:
    def __init__(self, metrics: dict[str, float], tags: dict[str, str]):
        self.metrics = metrics
        self.tags = tags


class _FakeRun:
    def __init__(self, metrics: dict[str, float], tags: dict[str, str]):
        self.data = _FakeRunData(metrics, tags)


class _FakeMlflowClient:
    """Duck-typed stand-in for `mlflow.tracking.MlflowClient` -- `list_versions`/
    `promote_version` only ever call `.search_model_versions`, `.get_run`,
    `.get_model_version`, `.get_latest_versions`, and
    `.transition_model_version_stage` on it."""

    def __init__(
        self, versions: list[_FakeVersion], runs: dict[str, _FakeRun], **_kwargs
    ):
        self._versions = versions
        self._runs = runs
        self.transitions: list[tuple[str, str, str, bool]] = []

    def search_model_versions(self, filter_string: str):
        return self._versions

    def get_run(self, run_id: str):
        return self._runs[run_id]

    def get_model_version(self, name: str, version: str):
        for v in self._versions:
            if v.version == version:
                return v
        from mlflow.exceptions import MlflowException

        raise MlflowException(f"version {version} not found")

    def get_latest_versions(self, name: str, stages: list[str]):
        return [v for v in self._versions if v.current_stage in stages]

    def transition_model_version_stage(
        self,
        name: str,
        version: str,
        stage: str,
        archive_existing_versions: bool = False,
    ):
        self.transitions.append((name, version, stage, archive_existing_versions))
        for v in self._versions:
            if v.version == version:
                v.current_stage = stage


class TestListVersions:
    async def test_returns_every_version_newest_first(self, monkeypatch):
        older = _FakeVersion(
            "2", "Archived", "run-2", creation_timestamp=1_700_000_000_000
        )
        newer = _FakeVersion(
            "3", "Production", "run-3", creation_timestamp=1_800_000_000_000
        )
        runs = {
            "run-2": _FakeRun({"test_mape": 5.1}, {"git_sha": "cafebabe"}),
            "run-3": _FakeRun({"test_mape": 4.2}, {"git_sha": "deadbeef"}),
        }
        monkeypatch.setattr(
            registry_module,
            "MlflowClient",
            lambda **kwargs: _FakeMlflowClient([older, newer], runs, **kwargs),
        )

        versions = await list_versions("lstm_demand")

        assert [v.version for v in versions] == ["3", "2"]
        assert versions[0].stage == "Production"
        assert versions[0].metrics == {"test_mape": 4.2}
        assert versions[0].git_sha == "deadbeef"
        assert versions[0].created_at == datetime.fromtimestamp(
            1_800_000_000_000 / 1000, tz=UTC
        )

    async def test_returns_empty_list_when_nothing_is_registered(self, monkeypatch):
        monkeypatch.setattr(
            registry_module,
            "MlflowClient",
            lambda **kwargs: _FakeMlflowClient([], {}, **kwargs),
        )

        versions = await list_versions("lstm_demand")

        assert versions == []

    async def test_git_sha_is_none_when_the_run_has_no_tag(self, monkeypatch):
        version = _FakeVersion(
            "1", "Staging", "run-1", creation_timestamp=1_700_000_000_000
        )
        runs = {"run-1": _FakeRun({}, {})}
        monkeypatch.setattr(
            registry_module,
            "MlflowClient",
            lambda **kwargs: _FakeMlflowClient([version], runs, **kwargs),
        )

        versions = await list_versions("lstm_demand")

        assert versions[0].git_sha is None


class TestPromoteVersion:
    async def test_promotes_a_better_candidate_and_archives_the_old_production(
        self, monkeypatch
    ):
        current_prod = _FakeVersion(
            "2", "Production", "run-2", creation_timestamp=1_700_000_000_000
        )
        candidate = _FakeVersion(
            "3", "Staging", "run-3", creation_timestamp=1_800_000_000_000
        )
        runs = {
            "run-2": _FakeRun({"test_mape": 5.0}, {}),
            "run-3": _FakeRun({"test_mape": 4.0}, {}),  # better (lower)
        }
        fake_client = _FakeMlflowClient([current_prod, candidate], runs)
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        summary = await promote_version("lstm_demand", "3", "Production")

        assert summary.stage == "Production"
        assert fake_client.transitions == [("lstm_demand", "3", "Production", True)]

    async def test_rejects_a_worse_candidate(self, monkeypatch):
        current_prod = _FakeVersion(
            "2", "Production", "run-2", creation_timestamp=1_700_000_000_000
        )
        candidate = _FakeVersion(
            "3", "Staging", "run-3", creation_timestamp=1_800_000_000_000
        )
        runs = {
            "run-2": _FakeRun({"test_mape": 4.0}, {}),
            "run-3": _FakeRun({"test_mape": 5.0}, {}),  # worse (higher)
        }
        fake_client = _FakeMlflowClient([current_prod, candidate], runs)
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        with pytest.raises(PromotionRejected):
            await promote_version("lstm_demand", "3", "Production")

        assert fake_client.transitions == []  # never called -- rejected first

    async def test_promotes_ungated_when_no_current_production_exists(
        self, monkeypatch
    ):
        candidate = _FakeVersion(
            "1", "Staging", "run-1", creation_timestamp=1_800_000_000_000
        )
        runs = {"run-1": _FakeRun({"test_mape": 9.9}, {})}
        fake_client = _FakeMlflowClient([candidate], runs)
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        summary = await promote_version("lstm_demand", "1", "Production")

        assert summary.stage == "Production"

    async def test_promotes_ungated_when_metrics_are_missing_on_either_side(
        self, monkeypatch
    ):
        current_prod = _FakeVersion(
            "2", "Production", "run-2", creation_timestamp=1_700_000_000_000
        )
        candidate = _FakeVersion(
            "3", "Staging", "run-3", creation_timestamp=1_800_000_000_000
        )
        runs = {
            "run-2": _FakeRun({}, {}),  # no test_mape logged
            "run-3": _FakeRun({"test_mape": 4.0}, {}),
        }
        fake_client = _FakeMlflowClient([current_prod, candidate], runs)
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        summary = await promote_version("lstm_demand", "3", "Production")

        assert summary.stage == "Production"

    async def test_staging_and_archived_transitions_are_not_gated(self, monkeypatch):
        current_prod = _FakeVersion(
            "2", "Production", "run-2", creation_timestamp=1_700_000_000_000
        )
        candidate = _FakeVersion(
            "3", "Staging", "run-3", creation_timestamp=1_800_000_000_000
        )
        runs = {
            "run-2": _FakeRun({"test_mape": 4.0}, {}),
            "run-3": _FakeRun({"test_mape": 99.0}, {}),  # much worse, but not promoting
        }
        fake_client = _FakeMlflowClient([current_prod, candidate], runs)
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        summary = await promote_version("lstm_demand", "3", "Archived")

        assert summary.stage == "Archived"
        assert fake_client.transitions == [("lstm_demand", "3", "Archived", False)]
