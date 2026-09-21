"""One-off: copy an already-trained run's weights/scalers/calibration/bias
correction + params/metrics from one MLflow tracking server into another,
registering it there as a new model version -- without re-running training.

Why this exists (2026-08-22): retraining directly against production's
MLflow (real Railway-hosted server + R2 credentials passed inline) as a
background process got killed by this environment partway through
training on a couple of TFT attempts, before any result existed to
register. Training once against the local dev MLflow (already reliable)
and then copying the *finished* result across is a much shorter,
lower-risk operation -- no long-lived background process holding
production credentials, just a few HTTP calls.

Usage (from services/forecast-api/):
    SRC_MLFLOW_TRACKING_URI=http://localhost:5001 \\
    SRC_MLFLOW_S3_ENDPOINT_URL=http://localhost:9000 \\
    SRC_AWS_ACCESS_KEY_ID=minioadmin \\
    SRC_AWS_SECRET_ACCESS_KEY=minioadmin \\
    DST_MLFLOW_TRACKING_URI=https://mlflow-production-d9db.up.railway.app \\
    DST_MLFLOW_S3_ENDPOINT_URL=https://<r2-endpoint> \\
    DST_AWS_ACCESS_KEY_ID=... \\
    DST_AWS_SECRET_ACCESS_KEY=... \\
    uv run python scripts/promote_run_to_registry.py <src_model_name> <src_version> <dst_model_name>
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import joblib
import mlflow
import torch
from mlflow.tracking import MlflowClient


def _set_env(prefix: str) -> None:
    for key in (
        "MLFLOW_TRACKING_URI",
        "MLFLOW_S3_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ):
        value = os.environ.get(f"{prefix}_{key}")
        if value is not None:
            os.environ[key] = value


def main() -> None:
    src_model_name, src_version, dst_model_name = sys.argv[1:4]

    _set_env("SRC")
    src_uri = os.environ["MLFLOW_TRACKING_URI"]
    src_client = MlflowClient(tracking_uri=src_uri)
    model_version = src_client.get_model_version(src_model_name, str(src_version))
    run_id = model_version.run_id
    assert run_id is not None
    run = src_client.get_run(run_id)
    params = dict(run.data.params)
    metrics = dict(run.data.metrics)
    tags = {
        k: v
        for k, v in run.data.tags.items()
        if not k.startswith("mlflow.")  # MLflow-internal tags aren't ours to copy
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        local_dir = mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path="serving", dst_path=tmpdir, tracking_uri=src_uri
        )
        state_dict = torch.load(
            Path(local_dir) / "model_state_dict.pt",
            map_location=torch.device("cpu"),
            weights_only=True,
        )
        feature_scalers = joblib.load(Path(local_dir) / "feature_scalers.joblib")
        target_scaler = joblib.load(Path(local_dir) / "target_scaler.joblib")

        # Real bug, hit live 2026-09-21 promoting into a fresh VPS
        # MLflow: `mlflow.artifacts.load_dict` has no `tracking_uri`
        # kwarg at all (unlike `download_artifacts`, which does) --
        # passing one raised `TypeError`, silently swallowed by the
        # bare `except Exception` below, leaving `calibration_dict`
        # `None` even when the source run genuinely has the file.
        # `load_bundle` (services/forecast-api's own model loader)
        # treats a missing `conformal_calibration.json` as a hard
        # error, unlike `demand_bias_correction.json` (deliberately
        # optional) -- so this silently produced a promoted model
        # version that could never actually be loaded. Fixed by relying
        # on the ambient `MLFLOW_TRACKING_URI` env var `_set_env("SRC")`
        # already set above, same as `download_artifacts` does one
        # level up without needing the kwarg either.
        calibration_dict = None
        try:
            calibration_dict = mlflow.artifacts.load_dict(
                f"runs:/{run_id}/conformal_calibration.json"
            )
        except Exception:
            pass

        bias_dict = None
        try:
            bias_dict = mlflow.artifacts.load_dict(
                f"runs:/{run_id}/demand_bias_correction.json"
            )
        except Exception:
            pass

    # Reconstruct the real model so mlflow.pytorch.log_model has a real
    # nn.Module to register from (register_model's normal path) -- the
    # architecture params needed vary by whether this is DemandTFT or
    # DemandLSTM, inferred from which params are present.
    if "n_encoder_features" in params:
        from app.models.tft import DemandTFT

        model: torch.nn.Module = DemandTFT(
            n_encoder_features=int(params["n_encoder_features"]),
            n_decoder_features=int(params["n_decoder_features"]),
            horizon=int(params["horizon"]),
            hidden_size=int(params["hidden_size"]),
            n_heads=int(params["n_heads"]),
            dropout=float(params["dropout"]),
        )
    else:
        from app.models.ml import DemandLSTM

        model = DemandLSTM(
            n_features=int(params["n_features"]),
            horizon=int(params["horizon"]),
            hidden_size=int(params["hidden_size"]),
            num_layers=int(params["num_layers"]),
            dropout=float(params["dropout"]),
        )
    model.load_state_dict(state_dict)
    model.eval()

    _set_env("DST")
    # boto3 lazily creates a process-global default session on first use
    # (the SRC-side download above already triggered that, with the SRC
    # creds baked in) -- overwriting os.environ afterwards doesn't get
    # picked up by that cached session, so every S3 call below would
    # silently keep using SRC's (MinIO) credentials against DST's (R2)
    # endpoint. Resetting it forces boto3 to build a fresh session from
    # the now-current env vars on next use.
    import boto3

    boto3.DEFAULT_SESSION = None

    dst_uri = os.environ["MLFLOW_TRACKING_URI"]
    mlflow.set_tracking_uri(dst_uri)

    with mlflow.start_run() as dst_run:
        mlflow.log_params(params)
        mlflow.log_param("promoted_from", f"{src_uri}::{src_model_name}::v{src_version}")
        if metrics:
            mlflow.log_metrics(metrics)
        run_tags = dict(tags)
        run_tags["promoted_from_run_id"] = run_id
        mlflow.set_tags(run_tags)

        mlflow.pytorch.log_model(model, artifact_path="model", serialization_format="pickle")

        with tempfile.TemporaryDirectory() as tmpdir:
            joblib.dump(feature_scalers, Path(tmpdir) / "feature_scalers.joblib")
            joblib.dump(target_scaler, Path(tmpdir) / "target_scaler.joblib")
            torch.save(model.state_dict(), Path(tmpdir) / "model_state_dict.pt")
            mlflow.log_artifacts(tmpdir, artifact_path="serving")

        if calibration_dict is not None:
            mlflow.log_dict(calibration_dict, "conformal_calibration.json")
        if bias_dict is not None:
            mlflow.log_dict(bias_dict, "demand_bias_correction.json")

        dst_run_id = dst_run.info.run_id

    from app.service.mlops.registry import register_model

    version = register_model(dst_run_id, dst_model_name)
    print(f"registered {dst_model_name} v{version.version} (run {dst_run_id}) at {dst_uri}")


if __name__ == "__main__":
    main()
