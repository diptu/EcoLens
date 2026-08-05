"""FastAPI dependency providers.

Thin wrappers around the module-level factories in `app.db.session`,
`app.db.redis`, and `app.core.config` -- `Depends` just needs an
async-generator / plain-callable shape around each of them. Ported
verbatim from data-pipeline's identical module.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.redis import get_redis
from app.db.session import get_session


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session() as session:
        yield session


def get_app_settings() -> Settings:
    return get_settings()


def get_redis_client() -> Redis:
    return get_redis()
