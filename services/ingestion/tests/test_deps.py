import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_db, get_redis_client
from app.core.config import Settings, get_settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_get_app_settings_returns_the_cached_settings():
    assert get_app_settings() is get_settings()
    assert isinstance(get_app_settings(), Settings)


def test_get_redis_client_returns_a_redis_instance():
    assert isinstance(get_redis_client(), Redis)


async def test_get_db_yields_an_async_session():
    agen = get_db()
    session = await agen.__anext__()
    try:
        assert isinstance(session, AsyncSession)
    finally:
        await agen.aclose()
