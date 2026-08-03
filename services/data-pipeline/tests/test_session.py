import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.db import session as db_session

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_caches():
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    db_session.get_sessionmaker.cache_clear()
    yield
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    db_session.get_sessionmaker.cache_clear()


def test_get_engine_uses_settings_database_url(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", ""
    )  # else the real .env's DATABASE_URL would win
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "testdb")

    engine = db_session.get_engine()

    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "postgresql+asyncpg"
    assert engine.url.host == "db.internal"
    assert engine.url.port == 5433
    assert engine.url.database == "testdb"


def test_get_engine_is_cached():
    assert db_session.get_engine() is db_session.get_engine()


def test_get_sessionmaker_binds_to_engine():
    maker = db_session.get_sessionmaker()
    session = maker()
    assert session.bind is db_session.get_engine()


async def test_get_session_commits_with_no_pending_work():
    async with db_session.get_session() as session:
        assert session.bind is db_session.get_engine()


async def test_dispose_is_safe_without_a_live_connection():
    await db_session.dispose()
