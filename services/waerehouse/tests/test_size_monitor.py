from contextlib import asynccontextmanager

import pytest

from app.core.config import get_settings
from app.retention import size_monitor

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, size_bytes):
        self._size_bytes = size_bytes

    async def execute(self, query, params=None):
        return _FakeResult((self._size_bytes,))


def _wire(monkeypatch, size_bytes):
    @asynccontextmanager
    async def get_session():
        yield _FakeSession(size_bytes)

    monkeypatch.setattr(size_monitor, "get_session", get_session)


async def test_ok_below_the_warning_threshold(monkeypatch):
    _wire(monkeypatch, size_bytes=100 * 1024 * 1024)  # 100MB of 500MB = 20%

    report = await size_monitor.check_database_size()

    assert report.severity == "ok"
    assert report.size_bytes == 100 * 1024 * 1024


async def test_warning_at_80_pct(monkeypatch):
    settings = get_settings()
    limit_bytes = settings.database_size_limit_mb * 1024 * 1024
    _wire(monkeypatch, size_bytes=int(limit_bytes * 0.85))

    report = await size_monitor.check_database_size()

    assert report.severity == "warning"


async def test_emergency_at_95_pct(monkeypatch):
    settings = get_settings()
    limit_bytes = settings.database_size_limit_mb * 1024 * 1024
    _wire(monkeypatch, size_bytes=int(limit_bytes * 0.97))

    report = await size_monitor.check_database_size()

    assert report.severity == "emergency"


async def test_pct_used_is_computed_against_the_configured_limit(monkeypatch):
    settings = get_settings()
    limit_bytes = settings.database_size_limit_mb * 1024 * 1024
    _wire(monkeypatch, size_bytes=limit_bytes // 2)

    report = await size_monitor.check_database_size()

    assert report.pct_used == pytest.approx(0.5, abs=0.01)
    assert report.limit_bytes == limit_bytes


async def test_updates_the_prometheus_gauge(monkeypatch):
    from app.core.metrics import database_size_bytes

    _wire(monkeypatch, size_bytes=42 * 1024 * 1024)

    await size_monitor.check_database_size()

    assert database_size_bytes._value.get() == 42 * 1024 * 1024
