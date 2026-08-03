"""MLflow model loading + hot-reload (`README.md`: "loads LSTM from
MLflow on boot"; "forecast-api hot-reloads it on the next request — no
service-to-service call, just a watch on the MLflow registry"; `TODO.md`'s
"Non-Blocking Training Architecture" checklist item on thread-safe
model hot-swapping).

`load_bundle` reconstructs `DemandLSTM` from its own copy of the class
(`models/ml.py`) plus the `state_dict`/scalers/calibration
`data-pipeline`'s `service/ml/train.py` persisted under the `serving` artifact
path — see `models/ml.py`'s docstring for why this is a `state_dict` load,
not `mlflow.pytorch.load_model`.

`ModelRegistry` holds the currently-served bundle behind a plain instance
attribute. A background task (`watch`, started in `main.py`'s
lifespan) polls MLflow on an interval and, when it finds a newer
`Production` version, builds the new bundle *first* and only then
reassigns `self._bundle` — a single attribute write, atomic under the
GIL, so an in-flight request reading `self._bundle` never observes a
half-constructed bundle. This is the "atomic pointer swap" pattern
`TODO.md`'s hot-swapping checklist item describes; it hasn't yet been
load-tested under real concurrent traffic (that verification is still
open, tracked there) but the swap mechanism itself is real, not a stub.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib
import mlflow
import mlflow.artifacts
import torch
from mlflow.tracking import MlflowClient
from sklearn.preprocessing import StandardScaler

from app.core.config import get_settings
from app.service.ml.conformal import ConformalCalibration
from app.models.ml import DemandLSTM
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class ModelBundle:
    model: DemandLSTM
    feature_scalers: dict[str, StandardScaler]
    target_scaler: StandardScaler
    calibration: ConformalCalibration
    run_id: str
    version: str
    stage: str
    loaded_at: datetime
    horizon: int
    lookback: int
    metrics: dict[str, float]
    git_sha: str | None


async def load_bundle(model_name: str, stage: str = "Production") -> ModelBundle | None:
    """`None` if `model_name` has no version in `stage` yet — a real,
    expected state before the first model is ever trained+promoted, not
    an error. Runs MLflow's (blocking) client calls in a worker thread
    (`asyncio.to_thread`) so this never blocks the event loop other
    requests are being served on, even though it's only ever called from
    the background watch loop / app startup, not from a request handler
    directly."""

    def _load() -> ModelBundle | None:
        tracking_uri = get_settings().mlflow_tracking_uri
        # `mlflow.artifacts.download_artifacts`/`load_dict` below resolve
        # `runs:/...` URIs against the *global* active tracking URI, not
        # a per-call parameter -- set it explicitly rather than relying
        # on whatever MLflow's own default happens to be (its built-in
        # fallback silently creates a local `mlflow.db`/`mlruns/` in the
        # process's cwd, not `Settings.mlflow_tracking_uri`).
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient(tracking_uri=tracking_uri)
        versions = client.get_latest_versions(model_name, stages=[stage])
        if not versions:
            return None
        version = versions[0]
        run = client.get_run(version.run_id)
        params = run.data.params
        metrics = run.data.metrics

        model = DemandLSTM(
            n_features=int(params["n_features"]),
            horizon=int(params["horizon"]),
            hidden_size=int(params["hidden_size"]),
            num_layers=int(params["num_layers"]),
            dropout=float(params["dropout"]),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            local_dir = mlflow.artifacts.download_artifacts(
                run_id=version.run_id, artifact_path="serving", dst_path=tmpdir
            )
            # weights_only=True: this file is always a plain state_dict
            # data-pipeline wrote via mlflow.artifacts (never an
            # externally-sourced file), but there's no reason to allow
            # arbitrary-object unpickling when only tensors are ever
            # stored here.
            state_dict = torch.load(
                Path(local_dir) / "model_state_dict.pt",
                map_location=torch.device("cpu"),
                weights_only=True,
            )
            feature_scalers = joblib.load(Path(local_dir) / "feature_scalers.joblib")
            target_scaler = joblib.load(Path(local_dir) / "target_scaler.joblib")

        model.load_state_dict(state_dict)
        model.eval()

        calibration_dict = mlflow.artifacts.load_dict(
            f"runs:/{version.run_id}/conformal_calibration.json"
        )

        return ModelBundle(
            model=model,
            feature_scalers=feature_scalers,
            target_scaler=target_scaler,
            calibration=ConformalCalibration.from_dict(calibration_dict),
            run_id=version.run_id,
            version=version.version,
            stage=stage,
            loaded_at=datetime.now(UTC),
            horizon=int(params["horizon"]),
            lookback=int(params["lookback"]),
            metrics=dict(metrics),
            git_sha=run.data.tags.get("git_sha"),
        )

    return await asyncio.to_thread(_load)


class ModelRegistry:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._bundle: ModelBundle | None = None

    @property
    def bundle(self) -> ModelBundle | None:
        return self._bundle

    async def refresh(self) -> bool:
        """Loads the current `Production` version and swaps it in if
        it's a different version than what's currently held. Returns
        whether a swap happened (used by `/v1/readyz` to report "model
        loaded" and by tests)."""
        new_bundle = await load_bundle(self.model_name)
        if new_bundle is None:
            return False
        if self._bundle is not None and self._bundle.version == new_bundle.version:
            return False
        self._bundle = new_bundle
        log.info(
            "registry.model_loaded",
            model_name=self.model_name,
            version=new_bundle.version,
            run_id=new_bundle.run_id,
        )
        return True

    async def watch(self, interval_seconds: float) -> None:
        """Long-running background loop — `main.py`'s lifespan starts
        this as an `asyncio.Task` and cancels it on shutdown. A failed
        refresh is logged and retried next interval, not raised — MLflow
        being briefly unreachable shouldn't crash request serving using
        the last-known-good bundle."""
        while True:
            try:
                await self.refresh()
            except Exception as exc:
                log.error(
                    "registry.refresh_failed",
                    model_name=self.model_name,
                    error=str(exc),
                )
            await asyncio.sleep(interval_seconds)
