"""Async Redis cache layer for forecast-api.

Purely additive: every method degrades to a no-op cache miss when
`redis_url` isn't configured or Redis is unreachable, so a missing or
unhealthy cache never turns into a request failure -- it just costs a
Postgres round-trip. Mirrors data-pipeline's
`ecolens.warehouse.api.cache.Cache`. Addresses forecast-api's TODO.md
ECO-P01 ("Implement Redis caching layer for `/forecast/latest`").
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from .logging import get_logger
from .settings import ForecastApiSettings

log = get_logger(__name__)


class Cache:
    """Async Redis cache. No-ops when Redis isn't configured/reachable."""

    def __init__(self, settings: ForecastApiSettings) -> None:
        self.settings = settings
        self._client: aioredis.Redis | None = None
        self._enabled = bool(settings.redis_url)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        if not self._enabled or self.settings.redis_url is None:
            return
        try:
            client = aioredis.from_url(self.settings.redis_url, decode_responses=True)
            await client.ping()
            self._client = client
            log.info("cache.connected", url=self.settings.redis_url)
        except Exception as exc:  # noqa: BLE001
            log.warning("cache.connect_failed", error=str(exc))
            self._client = None
            self._enabled = False

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(self, key: str) -> Any | None:
        if self._client is None:
            return None
        try:
            raw = await self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001
            log.debug("cache.get_failed", key=key, error=str(exc))
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if self._client is None:
            return
        try:
            await self._client.set(
                key,
                json.dumps(value, default=str),
                ex=ttl or self.settings.cache_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("cache.set_failed", key=key, error=str(exc))


__all__ = ["Cache"]
