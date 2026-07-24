"""Async PostgreSQL connection pool for the warehouse API.

Wraps `asyncpg.create_pool()` with a health check and statement-level
error handling. Every query helper in `queries.py` goes through this
class rather than touching asyncpg directly.
"""

from __future__ import annotations

import time
from typing import Any

import asyncpg
from fastapi import HTTPException

from ecolens.shared.observability.logging import get_logger

from .settings import WarehouseApiSettings

log = get_logger(__name__)


class ConnectionPool:
    """Async PostgreSQL connection pool with a health check."""

    def __init__(self, settings: WarehouseApiSettings) -> None:
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
            host="(dsn)" if self.settings.pg_dsn else self.settings.pg_host,
            port=self.settings.pg_port,
            db=self.settings.pg_database,
        )
        if self.settings.pg_dsn:
            self._pool = await asyncpg.create_pool(
                dsn=self.settings.pg_dsn,
                min_size=self.settings.pg_min_pool,
                max_size=self.settings.pg_max_pool,
                command_timeout=self.settings.pg_command_timeout_seconds,
            )
        else:
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

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if self._pool is None:
            raise HTTPException(
                status_code=503, detail="warehouse database unavailable"
            )
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
            return [dict(r) for r in rows]
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("pool.query_failed", error=str(exc))
            raise HTTPException(
                status_code=503, detail=f"warehouse query failed: {exc}"
            ) from exc

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if self._pool is None:
            raise HTTPException(
                status_code=503, detail="warehouse database unavailable"
            )
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("pool.queryrow_failed", error=str(exc))
            raise HTTPException(
                status_code=503, detail=f"warehouse query failed: {exc}"
            ) from exc

    async def fetchval(self, query: str, *args: Any) -> Any:
        if self._pool is None:
            raise HTTPException(
                status_code=503, detail="warehouse database unavailable"
            )
        try:
            async with self._pool.acquire() as conn:
                return await conn.fetchval(query, *args)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("pool.queryval_failed", error=str(exc))
            raise HTTPException(
                status_code=503, detail=f"warehouse query failed: {exc}"
            ) from exc


async def check_health() -> dict[str, Any]:
    """One-shot health check. Used by ops scripts / cron wrappers."""
    from .settings import get_warehouse_api_settings

    pool = ConnectionPool(get_warehouse_api_settings())
    try:
        await pool.connect()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    result = await pool.health()
    await pool.disconnect()
    return result


__all__ = ["ConnectionPool", "check_health"]
