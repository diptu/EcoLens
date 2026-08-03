import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core import logging as logging_module


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_structlog_config():
    """`configure_logging()` caches `sys.stdout` in structlog's
    `PrintLoggerFactory` the first time it runs, then no-ops on every
    later call (`_configured` guard). `click.testing.CliRunner` (used by
    `test_cli.py`) replaces `sys.stdout` with its own buffer for the
    duration of `invoke()` and closes it afterward — if that happens to
    be the first `configure_logging()` call in the session, every
    `log.info`/`log.error` call in every test that runs afterward blows
    up with "I/O operation on closed file", since structlog is still
    holding a reference to CliRunner's now-closed buffer. Force a fresh
    configure (against whatever `sys.stdout` actually is right now)
    before each test so no test's logging behaviour depends on what ran
    before it.
    """
    logging_module._configured = False
    logging_module.configure_logging()
