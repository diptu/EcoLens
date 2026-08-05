from __future__ import annotations

import pytest
import torch

from app.service.ml import divergence
from app.service.ml.divergence import (
    DEFAULT_DRIFT_THRESHOLD,
    check_drift,
    find_last_full_retrain_run_id,
    weight_norm_drift,
)


class TestWeightNormDrift:
    def test_zero_drift_for_identical_weights(self):
        state = {"w": torch.tensor([1.0, 2.0, 3.0])}

        assert weight_norm_drift(state, state) == pytest.approx(0.0)

    def test_matches_hand_computed_relative_l2(self):
        anchor = {"w": torch.tensor([3.0, 4.0])}  # ||anchor|| = 5
        candidate = {"w": torch.tensor([3.0, 8.0])}  # diff = [0, 4], ||diff|| = 4

        assert weight_norm_drift(candidate, anchor) == pytest.approx(4.0 / 5.0)

    def test_sums_across_multiple_tensors(self):
        anchor = {"a": torch.tensor([3.0, 4.0]), "b": torch.tensor([0.0])}
        candidate = {"a": torch.tensor([3.0, 4.0]), "b": torch.tensor([5.0])}
        # anchor norm = sqrt(9+16+0) = 5; diff norm = sqrt(0+0+25) = 5
        assert weight_norm_drift(candidate, anchor) == pytest.approx(1.0)

    def test_raises_on_key_mismatch(self):
        anchor = {"a": torch.tensor([1.0])}
        candidate = {"b": torch.tensor([1.0])}

        with pytest.raises(ValueError, match="different keys"):
            weight_norm_drift(candidate, anchor)

    def test_raises_on_shape_mismatch(self):
        anchor = {"a": torch.tensor([1.0, 2.0])}
        candidate = {"a": torch.tensor([1.0])}

        with pytest.raises(ValueError, match="shape mismatch"):
            weight_norm_drift(candidate, anchor)

    def test_zero_anchor_norm_with_zero_diff_is_zero_drift(self):
        anchor = {"a": torch.tensor([0.0, 0.0])}
        candidate = {"a": torch.tensor([0.0, 0.0])}

        assert weight_norm_drift(candidate, anchor) == pytest.approx(0.0)

    def test_zero_anchor_norm_with_nonzero_diff_is_infinite_drift(self):
        anchor = {"a": torch.tensor([0.0, 0.0])}
        candidate = {"a": torch.tensor([1.0, 0.0])}

        assert weight_norm_drift(candidate, anchor) == float("inf")


class _FakeExperiment:
    def __init__(self, experiment_id: str) -> None:
        self.experiment_id = experiment_id


class _FakeRunInfo:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id


class _FakeRunData:
    def __init__(self, tags: dict[str, str]) -> None:
        self.tags = tags


class _FakeRun:
    def __init__(self, run_id: str, tags: dict[str, str]) -> None:
        self.info = _FakeRunInfo(run_id)
        self.data = _FakeRunData(tags)


class _FakeVersion:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeClient:
    def __init__(
        self, runs: list[_FakeRun], versions_by_run: dict[str, list[str]]
    ) -> None:
        self._runs = runs
        self._versions_by_run = versions_by_run

    def get_experiment_by_name(self, name: str) -> _FakeExperiment | None:
        return _FakeExperiment("exp-1")

    def search_runs(self, experiment_ids, order_by=None, max_results=None):
        return self._runs

    def search_model_versions(self, filter_string: str):
        # filter_string is "run_id='<id>'" -- extract the id the same
        # crude way a real caller's test double would, since this fake
        # never talks to a real MLflow server.
        run_id = filter_string.split("'")[1]
        names = self._versions_by_run.get(run_id, [])
        return [_FakeVersion(n) for n in names]


class TestFindLastFullRetrainRunId:
    def test_returns_none_when_experiment_does_not_exist(self, monkeypatch):
        class _NoExperimentClient(_FakeClient):
            def get_experiment_by_name(self, name):
                return None

        monkeypatch.setattr(
            divergence, "MlflowClient", lambda: _NoExperimentClient([], {})
        )

        assert find_last_full_retrain_run_id("lstm_demand") is None

    def test_skips_incremental_runs_and_finds_the_first_full_one(self, monkeypatch):
        runs = [
            _FakeRun("run-incremental-2", {"training_type": "incremental"}),
            _FakeRun("run-incremental-1", {"training_type": "incremental"}),
            _FakeRun("run-full", {}),
        ]
        versions_by_run = {"run-full": ["lstm_demand"]}
        monkeypatch.setattr(
            divergence, "MlflowClient", lambda: _FakeClient(runs, versions_by_run)
        )

        result = find_last_full_retrain_run_id("lstm_demand")

        assert result == "run-full"

    def test_skips_full_runs_belonging_to_a_different_registered_model(
        self, monkeypatch
    ):
        runs = [
            _FakeRun("run-tft", {}),
            _FakeRun("run-lstm", {}),
        ]
        versions_by_run = {
            "run-tft": ["lstm_demand_tft"],
            "run-lstm": ["lstm_demand"],
        }
        monkeypatch.setattr(
            divergence, "MlflowClient", lambda: _FakeClient(runs, versions_by_run)
        )

        result = find_last_full_retrain_run_id("lstm_demand")

        assert result == "run-lstm"

    def test_returns_none_when_no_full_run_exists(self, monkeypatch):
        runs = [_FakeRun("run-incremental-1", {"training_type": "incremental"})]
        monkeypatch.setattr(divergence, "MlflowClient", lambda: _FakeClient(runs, {}))

        assert find_last_full_retrain_run_id("lstm_demand") is None


class TestCheckDrift:
    def test_returns_none_when_no_anchor_exists(self, monkeypatch):
        monkeypatch.setattr(
            divergence, "find_last_full_retrain_run_id", lambda model_name: None
        )

        result = check_drift({"w": torch.tensor([1.0])}, "lstm_demand")

        assert result is None

    def test_returns_a_real_report_when_an_anchor_exists(self, monkeypatch):
        anchor_state = {"w": torch.tensor([3.0, 4.0])}
        candidate_state = {"w": torch.tensor([3.0, 8.0])}

        monkeypatch.setattr(
            divergence,
            "find_last_full_retrain_run_id",
            lambda model_name: "anchor-run-1",
        )
        monkeypatch.setattr(
            divergence.mlflow.artifacts,
            "download_artifacts",
            lambda **kwargs: "/fake/dir",
        )
        monkeypatch.setattr(
            divergence.torch,
            "load",
            lambda path, map_location=None, weights_only=None: anchor_state,
        )

        report = check_drift(candidate_state, "lstm_demand", threshold=0.5)

        assert report is not None
        assert report.relative_l2_drift == pytest.approx(0.8)
        assert report.exceeded_threshold is True
        assert report.threshold == 0.5
        assert report.compared_against_run_id == "anchor-run-1"

    def test_uses_the_default_threshold_when_not_given(self, monkeypatch):
        anchor_state = {"w": torch.tensor([1.0])}
        candidate_state = {"w": torch.tensor([1.0])}

        monkeypatch.setattr(
            divergence,
            "find_last_full_retrain_run_id",
            lambda model_name: "anchor-run-1",
        )
        monkeypatch.setattr(
            divergence.mlflow.artifacts,
            "download_artifacts",
            lambda **kwargs: "/fake/dir",
        )
        monkeypatch.setattr(
            divergence.torch,
            "load",
            lambda path, map_location=None, weights_only=None: anchor_state,
        )

        report = check_drift(candidate_state, "lstm_demand")

        assert report is not None
        assert report.threshold == DEFAULT_DRIFT_THRESHOLD
