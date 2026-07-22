"""ECO-115 (registry client): registers trained model versions in the
MLflow Model Registry and moves them through the alias-based lifecycle
`forecast-api`'s model loader (ECO-F03/F04) polls.

Uses registered-model *aliases* (`client.set_registered_model_alias`),
not the older numeric-stage API (`transition_model_version_stage`) --
that API has been deprecated since MLflow 2.9 in favor of aliases, and
this is a from-scratch build with no existing callers to migrate, so
there's no reason to start on the deprecated path. Reassigning an
alias to a new version *is* the atomic hot-swap primitive `strategy.md`
describes ("Synchronization" -- data-pipeline promotes a version,
forecast-api polls and swaps): `models:/<name>@<alias>` always
resolves to whichever version the alias currently points at, so a
concurrent reader never sees a "half-promoted" state.

`Settings.model_registry_alias` (default `"production"`) is this
service's one alias; `forecast-api`'s `model_stage` setting (ECO-F02)
points at the same string.

Every training run (`training/train.py`, `training/tune.py`,
`training/online.py`) logs the model *twice*, via `log_model_artifacts`
below: once as a full pickled `DemandLSTM` (what `register()` points
the registry at, and what this service's own `load_by_alias` uses --
fine, since it's the same package/environment), and once as a plain
`state_dict` + `model_architecture.json` pair. That second, lighter
form is what `forecast-api` actually loads (see that service's
`forecasting/loader.py`) -- it deliberately does *not* depend on this
package, so it can't unpickle a `DemandLSTM` instance (pickle requires
the exact class importable at load time). A `state_dict` has no such
requirement: any correctly-shaped `nn.Module`, in any process, can load
it.
"""

from __future__ import annotations

from dataclasses import dataclass

import mlflow
from mlflow.entities.model_registry import ModelVersion
from mlflow.tracking import MlflowClient

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ..models.lstm import DemandLSTM

log = get_logger(__name__)


def log_model_artifacts(model: DemandLSTM) -> None:
    """Call once per training run, inside an active `mlflow.start_run()`
    block, before the run closes. See module docstring for why this
    logs the model twice.

    `pip_requirements=[]` skips `mlflow.pytorch.log_model`'s default
    behaviour of shelling out to `uv export` to capture a
    `requirements.txt` artifact -- ~7s per call, measured, entirely
    off the training critical path for no benefit here: nothing in
    this pipeline ever uses that artifact to recreate a virtualenv
    (`load_by_alias` below loads within this same, already-correct
    environment; `forecast-api` loads the separate `state_dict`
    artifact instead, with its own independently-pinned dependencies).
    """
    mlflow.pytorch.log_model(
        model, name="model", serialization_format="pickle", pip_requirements=[]
    )
    mlflow.pytorch.log_state_dict(model.state_dict(), artifact_path="model_state_dict")
    mlflow.log_dict(model.architecture_dict(), "model_architecture.json")


@dataclass(frozen=True)
class RegisteredVersion:
    name: str
    version: str
    run_id: str
    aliases: tuple[str, ...]


class ModelRegistry:
    """Thin wrapper over `MlflowClient` scoped to one registered model
    name (`Settings.mlflow_registered_model_name`) -- every method here
    is the one this service needs, not a general-purpose MLflow client
    facade.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        mlflow.set_tracking_uri(self.settings.mlflow_tracking_uri)
        self.client = MlflowClient(tracking_uri=self.settings.mlflow_tracking_uri)
        self.model_name = self.settings.mlflow_registered_model_name

    def register(
        self, run_id: str, *, artifact_path: str = "model"
    ) -> RegisteredVersion:
        """Registers the model already logged under `run_id`'s `artifact_path`
        (see `training/train.py`'s `mlflow.pytorch.log_model` call) as a
        new version of `self.model_name`. Does *not* assign any alias --
        that's `mlops/promote.py`'s decision, not this method's.
        """
        model_uri = f"runs:/{run_id}/{artifact_path}"
        mv = mlflow.register_model(model_uri, self.model_name)
        log.info(
            "registry.registered",
            name=self.model_name,
            version=mv.version,
            run_id=run_id,
        )
        return self._to_registered_version(mv)

    def set_alias(self, alias: str, version: str) -> None:
        """Points `alias` (e.g. `"production"`) at `version` -- the atomic
        hot-swap. Overwrites whatever the alias previously pointed at.
        """
        self.client.set_registered_model_alias(self.model_name, alias, version)
        log.info(
            "registry.alias_set", name=self.model_name, alias=alias, version=version
        )

    def get_by_alias(self, alias: str) -> RegisteredVersion | None:
        try:
            mv = self.client.get_model_version_by_alias(self.model_name, alias)
        except mlflow.exceptions.MlflowException:
            return None
        return self._to_registered_version(mv)

    def load_by_alias(self, alias: str, *, device: str = "cpu") -> DemandLSTM:
        """Loads the model version `alias` currently points at, with
        `map_location` fixed at load time -- `strategy.md` §3's
        GPU-trained/CPU-served portability, one call.
        """
        import torch

        model = mlflow.pytorch.load_model(
            f"models:/{self.model_name}@{alias}", map_location=torch.device(device)
        )
        if not isinstance(model, DemandLSTM):
            raise TypeError(
                f"models:/{self.model_name}@{alias} did not load as a DemandLSTM "
                f"(got {type(model).__name__}) -- registry may hold a model from "
                "an incompatible training run"
            )
        return model

    def list_versions(self) -> list[RegisteredVersion]:
        versions = self.client.search_model_versions(f"name='{self.model_name}'")
        return [self._to_registered_version(mv) for mv in versions]

    def _to_registered_version(self, mv: ModelVersion) -> RegisteredVersion:
        aliases = tuple(getattr(mv, "aliases", None) or ())
        return RegisteredVersion(
            name=mv.name,
            version=str(mv.version),
            run_id=mv.run_id or "",
            aliases=aliases,
        )


__all__ = ["ModelRegistry", "RegisteredVersion", "log_model_artifacts"]
