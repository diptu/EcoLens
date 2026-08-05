import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app
from app.core import logging as logging_module


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_real_dbt_build_watch(monkeypatch):
    """`app.main`'s lifespan starts a periodic `dbt build` background task
    (`dbt_build_watch.watch_and_build`) whenever `Settings.
    dbt_auto_build_interval_seconds > 0` (true by default) -- every test
    using the `client` fixture below runs the real lifespan, so without
    this, every one of those tests would spin up a real loop hitting
    Redis and a real `dbt build` subprocess. Mirrors forecast-api's
    `_no_real_mlflow_calls` fixture for the same reason. Returns
    immediately (a completed task is a safe no-op for `lifespan`'s
    `watch_task.cancel()` on shutdown) -- tests that want the real loop's
    behavior test `dbt_build_watch.watch_and_build` directly instead.
    """

    async def _fake_watch_and_build(redis, interval_seconds):
        return

    monkeypatch.setattr(app_main, "watch_and_build", _fake_watch_and_build)


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
