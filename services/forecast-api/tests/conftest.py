import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.service.ml.energy_registry import EnergyModelRegistry
from app.service.ml.registry import ModelRegistry
from app.core import logging as logging_module


@pytest.fixture(autouse=True)
def _no_real_mlflow_calls(monkeypatch):
    """The app's lifespan calls `ModelRegistry.refresh()` *and*
    `EnergyModelRegistry.refresh()` on startup and keeps polling both in
    the background (`ml/registry.py`, `ml/energy_registry.py`) -- real
    network calls to whatever `MLFLOW_TRACKING_URI` resolves to (its own
    default fallback if unset). Router tests don't want that: it's
    slow/flaky depending on the test machine's network state (a
    connection attempt to an unreachable host can hang for a long time
    under retry/backoff, not fail fast), and every test that needs a
    *loaded* bundle already overrides `get_model_registry`/
    `get_energy_model_registry` directly (see `test_model_endpoint.py`/
    `test_forecast.py`). Route MLflow entirely out of the picture for the
    ones that don't -- both registries, not just the first one (a real
    gap found live: `EnergyModelRegistry` was added after this fixture
    and silently wasn't covered by it, hanging every `client`-fixture
    test on a real MLflow call until this was fixed)."""

    async def _fake_refresh(self):
        return False

    monkeypatch.setattr(ModelRegistry, "refresh", _fake_refresh)
    monkeypatch.setattr(EnergyModelRegistry, "refresh", _fake_refresh)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_structlog_config():
    """Same rationale as data-pipeline's identical fixture: force a fresh
    `configure_logging()` before every test so no test's logging depends
    on what ran (or what closed `sys.stdout`) before it."""
    logging_module._configured = False
    logging_module.configure_logging()


@pytest.fixture(autouse=True)
def _clear_forecast_local_cache():
    """`GET /v1/forecast`'s L1 process-local cache (`app.core.local_cache`,
    `app.api.v1.forecast.routes.forecast_local_cache`) is a module-level
    singleton -- unlike Redis (a fresh `_FakeRedis()` per test), it isn't
    reconstructed per test on its own. Multiple tests reuse the same
    cache key (region + `bundle.version`, which most tests leave at the
    `_build_bundle` default of `"1"`), so without this an earlier test's
    cached response would leak into a later test that expects a fresh
    compute against its own fixture data."""
    from app.api.v1.forecast.routes import forecast_local_cache

    forecast_local_cache.clear()
    yield
    forecast_local_cache.clear()
