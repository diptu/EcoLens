import pytest
from fastapi.testclient import TestClient

from app.core import logging as logging_module
from app.main import app


TEST_ADMIN_TOKEN = "test-admin-token"


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch):
    """Admin-gated routes (`app/core/admin.py`) need a configured token;
    `client` presents it so existing route tests keep exercising the
    handler, not the gate. `anon_client` doesn't."""
    from app.core.config import get_settings

    monkeypatch.setenv("ADMIN_API_TOKEN", TEST_ADMIN_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app, headers={"X-Admin-Token": TEST_ADMIN_TOKEN}) as c:
        yield c


@pytest.fixture
def anon_client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_structlog_config():
    """Same rationale as data-pipeline/forecast-api's identical fixture:
    force a fresh `configure_logging()` before every test so no test's
    logging depends on what ran (or what closed `sys.stdout`) before it."""
    logging_module._configured = False
    logging_module.configure_logging()
