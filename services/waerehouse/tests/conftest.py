import pytest
from fastapi.testclient import TestClient

from app.core import logging as logging_module
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_structlog_config():
    """Force a fresh `configure_logging()` before every test so no
    test's logging depends on what ran (or what closed `sys.stdout`)
    before it -- same rationale as ingestion/data-pipeline/forecast-
    api's identical fixture."""
    logging_module._configured = False
    logging_module.configure_logging()
