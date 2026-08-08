"""MLflow model loading + hot-reload for `EnergyForecastLSTM` --
`service/ml/registry.py`'s counterpart for the multi-task model, kept as
a genuinely separate registry (not a generalisation of `ModelRegistry`)
because the two bundles carry structurally different fields (`demand_
scaler`/`generation_scaler`, no `calibration` -- `ml/train_energy_
forecast.py`'s own module docstring explains why this first pass has
none) and this service currently serves both the single-task
`lstm_demand` model and this one *simultaneously*, not as alternatives
-- `main.py`'s lifespan runs two independent registries/watch loops side
by side.
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
from app.core.logging import get_logger
from app.models.energy_forecast_lstm import EnergyForecastLSTM

log = get_logger(__name__)


@dataclass
class EnergyModelBundle:
    model: EnergyForecastLSTM
    feature_scalers: dict[str, StandardScaler]
    demand_scaler: StandardScaler
    generation_scaler: StandardScaler
    run_id: str
    version: str
    stage: str
    loaded_at: datetime
    horizon: int
    lookback: int
    generation_sources: int
    metrics: dict[str, float]
    git_sha: str | None


async def load_energy_bundle(model_name: str, stage: str = "Production") -> EnergyModelBundle | None:
    """Same shape/reasoning as `registry.load_bundle` -- `None` if
    `model_name` has no version in `stage` yet (real, expected before
    the first `train-energy-forecast` run is promoted)."""

    def _load() -> EnergyModelBundle | None:
        tracking_uri = get_settings().mlflow_tracking_uri
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient(tracking_uri=tracking_uri)
        versions = client.get_latest_versions(model_name, stages=[stage])
        if not versions:
            return None
        version = versions[0]
        run = client.get_run(version.run_id)
        params = run.data.params
        metrics = run.data.metrics

        model = EnergyForecastLSTM(
            input_features=int(params["n_features"]),
            horizon=int(params["horizon"]),
            hidden_size=int(params["hidden_size"]),
            num_layers=int(params["num_layers"]),
            dropout=float(params["dropout"]),
            generation_sources=int(params["generation_sources"]),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            local_dir = mlflow.artifacts.download_artifacts(
                run_id=version.run_id, artifact_path="serving", dst_path=tmpdir
            )
            state_dict = torch.load(
                Path(local_dir) / "model_state_dict.pt",
                map_location=torch.device("cpu"),
                weights_only=True,
            )
            feature_scalers = joblib.load(Path(local_dir) / "feature_scalers.joblib")
            demand_scaler = joblib.load(Path(local_dir) / "demand_scaler.joblib")
            generation_scaler = joblib.load(Path(local_dir) / "generation_scaler.joblib")

        model.load_state_dict(state_dict)
        model.eval()

        return EnergyModelBundle(
            model=model,
            feature_scalers=feature_scalers,
            demand_scaler=demand_scaler,
            generation_scaler=generation_scaler,
            run_id=version.run_id,
            version=version.version,
            stage=stage,
            loaded_at=datetime.now(UTC),
            horizon=int(params["horizon"]),
            lookback=int(params["lookback"]),
            generation_sources=int(params["generation_sources"]),
            metrics=dict(metrics),
            git_sha=run.data.tags.get("git_sha"),
        )

    return await asyncio.to_thread(_load)


class EnergyModelRegistry:
    """Same atomic-pointer-swap hot-reload shape as `registry.
    ModelRegistry` -- see that class's docstring."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._bundle: EnergyModelBundle | None = None

    @property
    def bundle(self) -> EnergyModelBundle | None:
        return self._bundle

    async def refresh(self) -> bool:
        new_bundle = await load_energy_bundle(self.model_name)
        if new_bundle is None:
            return False
        if self._bundle is not None and self._bundle.version == new_bundle.version:
            return False
        self._bundle = new_bundle
        log.info(
            "energy_registry.model_loaded",
            model_name=self.model_name,
            version=new_bundle.version,
            run_id=new_bundle.run_id,
        )
        return True

    async def watch(self, interval_seconds: float) -> None:
        while True:
            try:
                await self.refresh()
            except Exception as exc:
                log.error("energy_registry.refresh_failed", model_name=self.model_name, error=str(exc))
            await asyncio.sleep(interval_seconds)
