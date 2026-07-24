"""Integration tests for ecolens_forecast_api.forecasting.reload (ECO-F04/
F08, and root TODO's ECO-T04: "point the model loader at a real MLflow
registry, register two model versions, and confirm hot-reload picks up
the second without dropping in-flight requests") against a real local
MLflow store, same pattern as test_forecasting_loader.py.
"""

from __future__ import annotations

import asyncio

import mlflow
import pytest

from ecolens_forecast_api.forecasting.loader import ModelLoader
from ecolens_forecast_api.forecasting.model import DemandLSTM
from ecolens_forecast_api.forecasting.reload import ModelReloader
from ecolens_forecast_api.settings import ForecastApiSettings

ARCHITECTURE = {
    "n_features": 24,
    "hidden_size": 8,
    "num_layers": 1,
    "horizon": 48,
    "dropout": 0.0,
}
BROKEN_ARCHITECTURE = {
    **ARCHITECTURE,
    "hidden_size": 999,
}  # mismatched vs. its own state_dict, forces a load failure


@pytest.fixture
def settings(tmp_path, monkeypatch) -> ForecastApiSettings:
    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("reload_test")
    return ForecastApiSettings(
        mlflow_tracking_uri=uri,
        mlflow_registered_model_name="reload_test_model",
        model_alias="production",
        model_reload_interval_seconds=5,
        mlflow_http_timeout_seconds=5,
        mlflow_http_max_retries=0,
    )


def _register_version(
    settings: ForecastApiSettings, *, architecture: dict | None = None
) -> str:
    arch = architecture or ARCHITECTURE
    model = DemandLSTM(
        **ARCHITECTURE
    )  # always build a *valid* model to get real weights...
    with mlflow.start_run() as run:
        mlflow.pytorch.log_model(
            model, name="model", serialization_format="pickle", pip_requirements=[]
        )
        mlflow.pytorch.log_state_dict(
            model.state_dict(), artifact_path="model_state_dict"
        )
        mlflow.log_dict(
            arch, "model_architecture.json"
        )  # ...but log a possibly-mismatched architecture
        mlflow.log_dict(
            {"mean": [0.0] * 24, "std": [1.0] * 24, "columns": list(range(24))},
            "scaler.json",
        )
        run_id = run.info.run_id

    mv = mlflow.register_model(
        f"runs:/{run_id}/model", settings.mlflow_registered_model_name
    )
    client = mlflow.tracking.MlflowClient()
    client.set_registered_model_alias(
        settings.mlflow_registered_model_name, settings.model_alias, mv.version
    )
    return str(mv.version)


class TestModelReloader:
    @pytest.mark.asyncio
    async def test_reload_once_with_nothing_registered_is_a_noop(self, settings):
        reloader = ModelReloader(settings, loader=ModelLoader(settings))
        changed = await reloader.reload_once()
        assert changed is False
        assert reloader.state.current is None

    @pytest.mark.asyncio
    async def test_reload_once_loads_the_first_version(self, settings):
        v1 = _register_version(settings)
        reloader = ModelReloader(settings, loader=ModelLoader(settings))
        changed = await reloader.reload_once()
        assert changed is True
        assert reloader.state.current.version == v1
        assert reloader.state.last_reload_success is True

    @pytest.mark.asyncio
    async def test_reload_once_is_a_noop_when_version_unchanged(self, settings):
        _register_version(settings)
        reloader = ModelReloader(settings, loader=ModelLoader(settings))
        await reloader.reload_once()
        first_current = reloader.state.current
        changed_again = await reloader.reload_once()
        assert changed_again is False
        assert (
            reloader.state.current is first_current
        )  # exact same object, not just equal

    @pytest.mark.asyncio
    async def test_reload_picks_up_a_promoted_second_version(self, settings):
        """The actual ECO-T04 scenario: two versions registered, alias
        reassigned to the second, reload picks it up.
        """
        v1 = _register_version(settings)
        reloader = ModelReloader(settings, loader=ModelLoader(settings))
        await reloader.reload_once()
        assert reloader.state.current.version == v1

        v2 = _register_version(settings)  # this also reassigns the alias to v2
        assert v2 != v1
        changed = await reloader.reload_once()
        assert changed is True
        assert reloader.state.current.version == v2

    @pytest.mark.asyncio
    async def test_in_flight_reference_survives_a_concurrent_reload(self, settings):
        """Simulates a request holding a reference to `state.current`
        across an `await` while a reload happens concurrently -- the
        held reference must keep pointing at the *old* model, proving
        the swap is a new object, not an in-place mutation a concurrent
        reader could observe half-updated.
        """
        v1 = _register_version(settings)
        reloader = ModelReloader(settings, loader=ModelLoader(settings))
        await reloader.reload_once()

        held_reference = reloader.state.current  # a request "in flight" grabs this
        assert held_reference.version == v1

        _register_version(settings)  # promote v2 concurrently
        await reloader.reload_once()

        assert reloader.state.current is not held_reference
        assert held_reference.version == v1  # the in-flight request's copy is untouched

    @pytest.mark.asyncio
    async def test_sanity_check_rejects_a_broken_candidate_and_keeps_serving_the_old_one(
        self, settings
    ):
        v1 = _register_version(settings)
        reloader = ModelReloader(settings, loader=ModelLoader(settings))
        await reloader.reload_once()
        assert reloader.state.current.version == v1

        # A mismatched architecture makes load_state_dict fail inside
        # ModelLoader -> ModelLoadError -> reload_once() must keep v1.
        _register_version(settings, architecture=BROKEN_ARCHITECTURE)
        changed = await reloader.reload_once()

        assert changed is False
        assert reloader.state.current.version == v1  # still the last GOOD version
        assert reloader.state.last_reload_success is False
        assert reloader.state.last_reload_error is not None

    @pytest.mark.asyncio
    async def test_start_and_stop_manage_the_poll_loop(self, settings):
        _register_version(settings)
        reloader = ModelReloader(settings, loader=ModelLoader(settings))
        await reloader.start()
        assert (
            reloader.state.current is not None
        )  # loaded synchronously before start() returns
        assert reloader._task is not None
        assert not reloader._task.done()

        await reloader.stop()
        assert reloader._task is None

    @pytest.mark.asyncio
    async def test_poll_loop_reloads_on_its_own_schedule(self, settings, monkeypatch):
        monkeypatch.setattr(settings, "model_reload_interval_seconds", 0.05)
        reloader = ModelReloader(settings, loader=ModelLoader(settings))
        await reloader.start()  # nothing registered yet -- current stays None
        assert reloader.state.current is None

        _register_version(settings)
        # Poll for the condition rather than a single fixed sleep -- each
        # reload_once() does real (if local) MLflow I/O, so its wall-clock
        # time varies with system load; a blind `sleep(0.2)` is exactly
        # the kind of timing assumption that's fine in isolation and
        # flaky under a busy full-suite run.
        for _ in range(100):  # up to ~5s
            if reloader.state.current is not None:
                break
            await asyncio.sleep(0.05)
        await reloader.stop()

        assert reloader.state.current is not None
