import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.service.ml.registry import ModelRegistry
from app.core import logging as logging_module


@pytest.fixture(autouse=True)
def _no_real_mlflow_calls(monkeypatch):
    """The app's lifespan calls `ModelRegistry.refresh()` on startup and
    keeps polling in the background (`ml/registry.py`) -- a real network
    call to whatever `MLFLOW_TRACKING_URI` resolves to (its own default
    fallback if unset). Router tests don't want that: it's slow/flaky
    depending on the test machine's network state (a connection attempt
    to an unreachable host can hang for a long time under retry/backoff,
    not fail fast), and every test that needs a *loaded* bundle already
    overrides `get_model_registry` directly (see `test_model_endpoint.py`/
    `test_forecast.py`). Route MLflow entirely out of the picture for the
    ones that don't."""

    async def _fake_refresh(self):
        return False

    monkeypatch.setattr(ModelRegistry, "refresh", _fake_refresh)


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
