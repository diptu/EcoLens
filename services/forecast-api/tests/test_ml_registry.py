from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.service.ml import registry as registry_module
from app.service.ml.registry import (
    DeletionRejected,
    LossCurvePoint,
    ModelRegistry,
    PromotionRejected,
    delete_model_version,
    get_loss_curve,
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
        async def fake_load_bundle(model_name, stage="Production", architecture="lstm"):
            return _FakeBundle("1")

        monkeypatch.setattr(registry_module, "load_bundle", fake_load_bundle)
        registry = ModelRegistry("lstm_demand")

        swapped = await registry.refresh()

        assert swapped is True
        assert registry.bundle.version == "1"

    async def test_does_not_swap_when_version_is_unchanged(self, monkeypatch):
        call_count = {"n": 0}

        async def fake_load_bundle(model_name, stage="Production", architecture="lstm"):
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

        async def fake_load_bundle(model_name, stage="Production", architecture="lstm"):
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
        async def fake_load_bundle(model_name, stage="Production", architecture="lstm"):
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
    def __init__(
        self,
        version: str,
        stage: str,
        run_id: str,
        creation_timestamp: int,
        tags: dict[str, str] | None = None,
    ):
        self.version = version
        self.current_stage = stage
        self.run_id = run_id
        self.creation_timestamp = creation_timestamp
        self.tags = tags or {}


class _FakeRunData:
    def __init__(self, metrics: dict[str, float], tags: dict[str, str]):
        self.metrics = metrics
        self.tags = tags


class _FakeRun:
    def __init__(self, metrics: dict[str, float], tags: dict[str, str]):
        self.data = _FakeRunData(metrics, tags)


class _FakeMetric:
    def __init__(self, step: int, value: float):
        self.step = step
        self.value = value


class _FakeMlflowClient:
    """Duck-typed stand-in for `mlflow.tracking.MlflowClient` -- `list_versions`/
    `promote_version`/`get_loss_curve`/`delete_model_version` only ever
    call `.search_model_versions`, `.get_run`, `.get_model_version`,
    `.get_latest_versions`, `.get_metric_history`,
    `.transition_model_version_stage`, and `.delete_model_version` on it."""

    def __init__(
        self,
        versions: list[_FakeVersion],
        runs: dict[str, _FakeRun],
        metric_history: dict[str, dict[str, list[_FakeMetric]]] | None = None,
        **_kwargs,
    ):
        self._versions = versions
        self._runs = runs
        self._metric_history = metric_history or {}
        self.transitions: list[tuple[str, str, str, bool]] = []
        self.deletions: list[tuple[str, str]] = []

    def search_model_versions(self, filter_string: str):
        return self._versions

    def get_run(self, run_id: str):
        return self._runs[run_id]

    def get_metric_history(self, run_id: str, key: str):
        return self._metric_history.get(run_id, {}).get(key, [])

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

    def delete_model_version(self, name: str, version: str):
        self.deletions.append((name, version))
        self._versions = [v for v in self._versions if v.version != version]


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


class TestGetLossCurve:
    async def test_merges_train_loss_val_loss_and_val_mape_by_epoch(self, monkeypatch):
        version = _FakeVersion(
            "3", "Production", "run-3", creation_timestamp=1_800_000_000_000
        )
        runs = {"run-3": _FakeRun({"test_mape": 4.2}, {})}
        metric_history = {
            "run-3": {
                "train_loss": [_FakeMetric(0, 120.5), _FakeMetric(1, 95.2)],
                "val_loss": [_FakeMetric(0, 130.0), _FakeMetric(1, 101.4)],
                "val_mape": [_FakeMetric(0, 12.1), _FakeMetric(1, 9.8)],
                "val_rmse": [_FakeMetric(0, 610.2), _FakeMetric(1, 480.7)],
                "val_mae": [_FakeMetric(0, 505.1), _FakeMetric(1, 390.4)],
            }
        }
        monkeypatch.setattr(
            registry_module,
            "MlflowClient",
            lambda **kwargs: _FakeMlflowClient(
                [version], runs, metric_history=metric_history, **kwargs
            ),
        )

        curve = await get_loss_curve("lstm_demand", "3")

        assert curve.run_id == "run-3"
        assert curve.points == [
            LossCurvePoint(
                epoch=0,
                train_loss=120.5,
                val_loss=130.0,
                val_mape=12.1,
                val_rmse=610.2,
                val_mae=505.1,
            ),
            LossCurvePoint(
                epoch=1,
                train_loss=95.2,
                val_loss=101.4,
                val_mape=9.8,
                val_rmse=480.7,
                val_mae=390.4,
            ),
        ]

    async def test_merges_by_union_not_intersection_of_steps(self, monkeypatch):
        # `val_loss`/`val_mape`/`val_rmse`/`val_mae` missing at a step
        # `train_loss` has (or vice versa) must still produce a point --
        # not silently dropped.
        version = _FakeVersion(
            "1", "Staging", "run-1", creation_timestamp=1_700_000_000_000
        )
        runs = {"run-1": _FakeRun({}, {})}
        metric_history = {
            "run-1": {
                "train_loss": [_FakeMetric(0, 50.0)],
                "val_loss": [],
                "val_mape": [],
                "val_rmse": [],
                "val_mae": [],
            }
        }
        monkeypatch.setattr(
            registry_module,
            "MlflowClient",
            lambda **kwargs: _FakeMlflowClient(
                [version], runs, metric_history=metric_history, **kwargs
            ),
        )

        curve = await get_loss_curve("lstm_demand", "1")

        assert curve.points == [
            LossCurvePoint(
                epoch=0,
                train_loss=50.0,
                val_loss=None,
                val_mape=None,
                val_rmse=None,
                val_mae=None,
            )
        ]

    async def test_val_loss_absent_for_a_version_trained_before_it_existed(
        self, monkeypatch
    ):
        # A version registered before `val_loss`/`val_rmse`/`val_mae`
        # were logged (2026-08-05) -- real absence, not backfilled with
        # a fabricated value.
        version = _FakeVersion(
            "1", "Production", "run-1", creation_timestamp=1_700_000_000_000
        )
        runs = {"run-1": _FakeRun({}, {})}
        metric_history = {
            "run-1": {
                "train_loss": [_FakeMetric(0, 50.0)],
                "val_mape": [_FakeMetric(0, 8.0)],
                # no "val_loss"/"val_rmse"/"val_mae" keys at all --
                # get_metric_history for them returns [] via
                # _FakeMlflowClient's own .get() default.
            }
        }
        monkeypatch.setattr(
            registry_module,
            "MlflowClient",
            lambda **kwargs: _FakeMlflowClient(
                [version], runs, metric_history=metric_history, **kwargs
            ),
        )

        curve = await get_loss_curve("lstm_demand", "1")

        assert curve.points == [
            LossCurvePoint(
                epoch=0,
                train_loss=50.0,
                val_loss=None,
                val_mape=8.0,
                val_rmse=None,
                val_mae=None,
            )
        ]

    async def test_returns_no_points_when_nothing_was_logged(self, monkeypatch):
        # A version trained before per-epoch logging existed -- real,
        # expected state, not an error.
        version = _FakeVersion(
            "1", "Staging", "run-1", creation_timestamp=1_700_000_000_000
        )
        runs = {"run-1": _FakeRun({}, {})}
        monkeypatch.setattr(
            registry_module,
            "MlflowClient",
            lambda **kwargs: _FakeMlflowClient([version], runs, **kwargs),
        )

        curve = await get_loss_curve("lstm_demand", "1")

        assert curve.run_id == "run-1"
        assert curve.points == []

    async def test_raises_for_an_unknown_version(self, monkeypatch):
        from mlflow.exceptions import MlflowException

        monkeypatch.setattr(
            registry_module,
            "MlflowClient",
            lambda **kwargs: _FakeMlflowClient([], {}, **kwargs),
        )

        with pytest.raises(MlflowException):
            await get_loss_curve("lstm_demand", "999")


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

    async def test_rejects_a_candidate_that_failed_its_live_evaluation_gate(
        self, monkeypatch
    ):
        candidate = _FakeVersion(
            "3",
            "Staging",
            "run-3",
            creation_timestamp=1_800_000_000_000,
            tags={"eval_gate_passed": "False", "eval_gate_mape": "23.5000"},
        )
        runs = {"run-3": _FakeRun({"test_mape": 4.0}, {})}
        fake_client = _FakeMlflowClient([candidate], runs)
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        with pytest.raises(PromotionRejected, match="live evaluation gate"):
            await promote_version("lstm_demand", "3", "Production")

        assert fake_client.transitions == []

    async def test_promotes_when_the_live_evaluation_gate_passed(self, monkeypatch):
        candidate = _FakeVersion(
            "3",
            "Staging",
            "run-3",
            creation_timestamp=1_800_000_000_000,
            tags={"eval_gate_passed": "True", "eval_gate_mape": "3.5000"},
        )
        runs = {"run-3": _FakeRun({"test_mape": 4.0}, {})}
        fake_client = _FakeMlflowClient([candidate], runs)
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        summary = await promote_version("lstm_demand", "3", "Production")

        assert summary.stage == "Production"

    async def test_promotes_ungated_when_no_eval_gate_tag_exists(self, monkeypatch):
        """An older version (registered before Phase 4, or a full
        retrain that never went through the incremental live-eval-gate
        path) has no `eval_gate_passed` tag at all -- ungated is the
        honest behavior, not a silent rejection for a check that never
        actually ran."""
        candidate = _FakeVersion(
            "3", "Staging", "run-3", creation_timestamp=1_800_000_000_000
        )
        runs = {"run-3": _FakeRun({"test_mape": 4.0}, {})}
        fake_client = _FakeMlflowClient([candidate], runs)
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


class TestDeleteModelVersion:
    async def test_deletes_a_non_production_version(self, monkeypatch):
        candidate = _FakeVersion(
            "2", "Staging", "run-2", creation_timestamp=1_700_000_000_000
        )
        runs = {"run-2": _FakeRun({}, {})}
        fake_client = _FakeMlflowClient([candidate], runs)
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        await delete_model_version("lstm_demand", "2")

        assert fake_client.deletions == [("lstm_demand", "2")]

    async def test_deletes_an_archived_version(self, monkeypatch):
        candidate = _FakeVersion(
            "2", "Archived", "run-2", creation_timestamp=1_700_000_000_000
        )
        runs = {"run-2": _FakeRun({}, {})}
        fake_client = _FakeMlflowClient([candidate], runs)
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        await delete_model_version("lstm_demand", "2")

        assert fake_client.deletions == [("lstm_demand", "2")]

    async def test_deletes_a_none_stage_version(self, monkeypatch):
        candidate = _FakeVersion(
            "5", "None", "run-5", creation_timestamp=1_800_000_000_000
        )
        runs = {"run-5": _FakeRun({}, {})}
        fake_client = _FakeMlflowClient([candidate], runs)
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        await delete_model_version("lstm_demand", "5")

        assert fake_client.deletions == [("lstm_demand", "5")]

    async def test_rejects_deleting_the_current_production_version(self, monkeypatch):
        candidate = _FakeVersion(
            "1", "Production", "run-1", creation_timestamp=1_700_000_000_000
        )
        runs = {"run-1": _FakeRun({}, {})}
        fake_client = _FakeMlflowClient([candidate], runs)
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        with pytest.raises(DeletionRejected, match="Production"):
            await delete_model_version("lstm_demand", "1")

        assert fake_client.deletions == []  # never called -- rejected first

    async def test_raises_for_an_unknown_version(self, monkeypatch):
        from mlflow.exceptions import MlflowException

        fake_client = _FakeMlflowClient([], {})
        monkeypatch.setattr(
            registry_module, "MlflowClient", lambda **kwargs: fake_client
        )

        with pytest.raises(MlflowException):
            await delete_model_version("lstm_demand", "999")
