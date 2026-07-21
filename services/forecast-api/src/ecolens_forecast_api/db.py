"""Async PostgreSQL connection pool for forecast-api.

Wraps `asyncpg.create_pool()` with a health check and statement-level
error handling. Mirrors data-pipeline's
`ecolens.warehouse.api.db.ConnectionPool` (resilient startup: a
down/unreachable Postgres degrades `/health` and 503s data routes
instead of crash-looping the process).
"""

from __future__ import annotations

import time
from typing import Any

import asyncpg
from fastapi import HTTPException

from .logging import get_logger
from .settings import ForecastApiSettings

log = get_logger(__name__)


class ConnectionPool:
    """Async PostgreSQL connection pool with a health check."""

    def __init__(self, settings: ForecastApiSettings) -> None:
        self.settings = settings
        self._pool: asyncpg.Pool | None = None

    @property
    def is_connected(self) -> bool:
        return self._pool is not None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        log.info(
            "pool.connect",
            host=self.settings.pg_host,
            port=self.settings.pg_port,
            db=self.settings.pg_database,
        )
        self._pool = await asyncpg.create_pool(
            host=self.settings.pg_host,
            port=self.settings.pg_port,
            database=self.settings.pg_database,
            user=self.settings.pg_user,
            password=self.settings.pg_password,
            min_size=self.settings.pg_min_pool,
            max_size=self.settings.pg_max_pool,
            command_timeout=self.settings.pg_command_timeout_seconds,
        )
        log.info(
            "pool.connected",
            size=f"{self.settings.pg_min_pool}-{self.settings.pg_max_pool}",
        )

    async def disconnect(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            log.info("pool.disconnected")

    async def health(self) -> dict[str, Any]:
        """Check connection health. Returns dict with status + latency."""
        if self._pool is None:
            return {"status": "unavailable", "reason": "pool not initialized"}
        start = time.perf_counter()
        try:
            async with self._pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
            latency_ms = (time.perf_counter() - start) * 1000
            return {
                "status": "ok" if result == 1 else "degraded",
                "latency_ms": round(latency_ms, 2),
                "pool_min": self.settings.pg_min_pool,
                "pool_max": self.settings.pg_max_pool,
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if self._pool is None:
            raise HTTPException(status_code=503, detail="forecast database unavailable")
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("pool.queryrow_failed", error=str(exc))
            raise HTTPException(
                status_code=503, detail=f"forecast query failed: {exc}"
            ) from exc


__all__ = ["ConnectionPool"]
