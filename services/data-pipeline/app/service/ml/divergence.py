"""Catastrophic-forgetting guard (`todo-model-training.md` Phase 4) —
a real weight-norm drift metric between an incremental fine-tune's
resulting weights and the last *full* retrain's weights, tracked over
time so a real alert can trip if incremental drift compounds too far
between full-retrain resets.

Architecture-agnostic: operates on plain `state_dict`s (`dict[str,
torch.Tensor]`), the same portable representation `ml/train.py`'s
`log_and_register_run` already persists as the `serving/
model_state_dict.pt` artifact for both `DemandLSTM` and `DemandTFT` —
this module never imports either model class.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import mlflow.artifacts
import torch
from mlflow.tracking import MlflowClient

from app.service.mlops.tracking import EXPERIMENT_NAME

# Relative L2 drift: ||incremental - full_retrain|| / ||full_retrain|| --
# scale-free (doesn't depend on the model's raw weight magnitudes, so the
# same threshold means the same thing for a small LSTM and a larger TFT),
# and 0 for identical weights, growing unboundedly as the incremental
# path wanders from its last known-good anchor. 0.5 (50% relative drift)
# is a real, if somewhat arbitrary, starting threshold -- deliberately
# conservative (trips before the incremental path has "replaced" half
# the anchor's weight norm), tunable via `Settings` once real incremental
# runs generate enough history to calibrate it against.
DEFAULT_DRIFT_THRESHOLD = 0.5


@dataclass
class DriftReport:
    relative_l2_drift: float
    exceeded_threshold: bool
    threshold: float
    compared_against_run_id: str


def weight_norm_drift(
    candidate: dict[str, torch.Tensor], anchor: dict[str, torch.Tensor]
) -> float:
    """Relative L2 drift of `candidate`'s weights from `anchor`'s --
    `sqrt(sum((candidate[k] - anchor[k])**2)) / sqrt(sum(anchor[k]**2))`
    across every shared tensor. Raises `ValueError` if `candidate` and
    `anchor` don't have the exact same keys/shapes (comparing an
    incremental fine-tune against anything but its own architecture's
    last full retrain is a caller bug, not a case to silently skip
    mismatched tensors for).
    """
    if candidate.keys() != anchor.keys():
        raise ValueError(
            "candidate and anchor state_dicts have different keys -- "
            "can only compare a fine-tune against its own architecture's "
            "last full retrain"
        )

    diff_sq_sum = 0.0
    anchor_sq_sum = 0.0
    for key, anchor_tensor in anchor.items():
        candidate_tensor = candidate[key]
        if candidate_tensor.shape != anchor_tensor.shape:
            raise ValueError(
                f"shape mismatch on {key!r}: candidate={tuple(candidate_tensor.shape)} "
                f"anchor={tuple(anchor_tensor.shape)}"
            )
        diff_sq_sum += float(
            torch.sum((candidate_tensor.float() - anchor_tensor.float()) ** 2)
        )
        anchor_sq_sum += float(torch.sum(anchor_tensor.float() ** 2))

    if anchor_sq_sum == 0.0:
        return 0.0 if diff_sq_sum == 0.0 else float("inf")
    return (diff_sq_sum**0.5) / (anchor_sq_sum**0.5)


def find_last_full_retrain_run_id(model_name: str) -> str | None:
    """The most recent MLflow run for `model_name` whose `training_type`
    tag is anything other than `"incremental"` (i.e. absent, or an
    explicit non-incremental value) — `ml/train.py`'s
    `train_and_register`/`train_tft.py`'s `train_and_register_tft` never
    tag `training_type` at all; only `ml.incremental`/a future
    `incremental_tft` do, specifically so this query can tell them apart.
    `None` if `model_name` has no runs yet (a real, expected state before
    the first full retrain)."""
    client = MlflowClient()
    # Every architecture's training run lands in this one shared
    # experiment (`mlops.tracking.configure_mlflow` always calls
    # `mlflow.set_experiment(EXPERIMENT_NAME)` regardless of which model
    # is being trained -- LSTM/TFT runs are told apart by registered
    # model name + `architecture` tag, not by experiment).
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
    if experiment is None:
        return None
    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        order_by=["start_time DESC"],
        max_results=200,
    )
    for run in runs:
        if run.data.tags.get("training_type") != "incremental":
            # A run belongs to `model_name` if it produced a registered
            # version of it -- cheaper to check via the registry than to
            # filter MLflow's run search on a param this experiment's
            # runs don't consistently log the registry target under.
            versions = client.search_model_versions(f"run_id='{run.info.run_id}'")
            if any(v.name == model_name for v in versions):
                return run.info.run_id
    return None


def check_drift(
    candidate_state_dict: dict[str, torch.Tensor],
    model_name: str,
    *,
    threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> DriftReport | None:
    """Real drift check for an incremental fine-tune's resulting weights
    against `model_name`'s last full retrain. `None` (not raised) if
    there's no full retrain to compare against yet -- the very first
    incremental run after a fresh registry has nothing to have drifted
    from, which is a real, expected state, not an error.
    """
    anchor_run_id = find_last_full_retrain_run_id(model_name)
    if anchor_run_id is None:
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        local_dir = mlflow.artifacts.download_artifacts(
            run_id=anchor_run_id, artifact_path="serving", dst_path=tmpdir
        )
        anchor_state_dict = torch.load(
            Path(local_dir) / "model_state_dict.pt",
            map_location=torch.device("cpu"),
            weights_only=True,
        )

    drift = weight_norm_drift(candidate_state_dict, anchor_state_dict)
    return DriftReport(
        relative_l2_drift=drift,
        exceeded_threshold=drift > threshold,
        threshold=threshold,
        compared_against_run_id=anchor_run_id,
    )
