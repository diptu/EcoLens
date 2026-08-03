"""MLflow model registry (`README.md` § MLflow: "Model registry stages:
`None -> Staging -> Production -> Archived`. Promotion is CI-gated").

Uses `MlflowClient.transition_model_version_stage` — MLflow's newer
alias-based registry API (`set_registered_model_alias`) is what MLflow
itself now recommends and `transition_model_version_stage` is formally
deprecated as of MLflow 2.9, but the stage model is what `README.md` and
`scripts/promote_model.sh` are both written against; migrating to aliases
is a real, deliberate follow-up, not something to silently swap in here
without updating the docs/scripts that describe stages.
"""

from __future__ import annotations

import mlflow
from mlflow.entities.model_registry import ModelVersion
from mlflow.tracking import MlflowClient

Stage = str  # "None" | "Staging" | "Production" | "Archived" -- MLflow's own type is a bare str


def register_model(
    run_id: str, model_name: str, artifact_path: str = "model"
) -> ModelVersion:
    """Register the model logged at `runs:/{run_id}/{artifact_path}` (by
    `mlflow.pytorch.log_model`, `ml/train.py`) as a new version of
    `model_name`, starting in the `None` stage."""
    return mlflow.register_model(f"runs:/{run_id}/{artifact_path}", model_name)


def transition_stage(
    model_name: str, version: str | int, stage: Stage, *, archive_existing: bool = True
) -> ModelVersion:
    """Move `version` of `model_name` to `stage`. `archive_existing=True`
    (the default) auto-archives whatever was previously in that stage —
    the usual case for `Production` (exactly one version should be
    serving); pass `False` for `Staging`, where having several candidates
    at once under evaluation is normal."""
    client = MlflowClient()
    return client.transition_model_version_stage(
        name=model_name,
        version=str(version),
        stage=stage,
        archive_existing_versions=archive_existing,
    )


def get_version_in_stage(model_name: str, stage: Stage) -> ModelVersion | None:
    """The current version of `model_name` in `stage`, or `None` if
    nothing's there — `forecast-api`'s model loader calls this with
    `stage="Production"` on every reload check (`ml/registry.py` in that
    service)."""
    client = MlflowClient()
    versions = client.get_latest_versions(model_name, stages=[stage])
    return versions[0] if versions else None
