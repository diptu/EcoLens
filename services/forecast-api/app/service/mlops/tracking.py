"""MLflow experiment tracking (`README.md` § MLflow: "every run -> MLflow
(params, metrics, git SHA, model signature, artifact store)").

`configure_mlflow` just points the `mlflow` SDK at `Settings.
mlflow_tracking_uri` and the one experiment this repo trains — it doesn't
start a tracking server. `docker-compose.yml`'s `mlflow` service (Postgres
backend store + MinIO/S3 artifact root) is the deployed target; for local/
CI use, any reachable MLflow server works the same way (`mlflow server
--backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlruns`
needs no Postgres/MinIO at all) — this module doesn't care which.
"""

from __future__ import annotations

import subprocess  # nosec B404 -- only used below for a fixed, argument-list (no shell) `git rev-parse HEAD` call

import mlflow

from app.core.config import Settings

EXPERIMENT_NAME = "lstm_demand"


def configure_mlflow(settings: Settings) -> None:
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)


def git_sha() -> str | None:
    """The commit `ml/train.py` ran from, for the run's tags — `None`
    (not raised) outside a git checkout or if `git` isn't on `PATH`, since
    a training run failing over a tag is worse than a run with one less
    tag."""
    try:
        result = subprocess.run(  # nosec B603 B607 -- fixed argument list, no shell, no user input; relies on `git` being resolvable on PATH same as any other git-dependent tooling in this repo
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return None
