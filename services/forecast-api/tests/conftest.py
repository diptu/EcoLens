"""Shared pytest fixtures/test doubles for the forecast-api test suite."""

from __future__ import annotations

from typing import Any


class FakeConnectionPool:
    """Duck-typed stand-in for `ecolens_forecast_api.db.ConnectionPool`."""

    def __init__(
        self,
        *,
        fetchrow_result: dict[str, Any] | None = None,
        fetch_result: list[dict[str, Any]] | None = None,
        connected: bool = True,
    ) -> None:
        self.is_connected = connected
        self._fetchrow_result = fetchrow_result
        self._fetch_result = fetch_result if fetch_result is not None else []
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.calls.append((query, args))
        return self._fetchrow_result

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append((query, args))
        return self._fetch_result


class FakeCache:
    """Duck-typed stand-in for `ecolens_forecast_api.cache.Cache`."""

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self.connected = enabled
        self._store: dict[str, Any] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, Any]] = []

    async def get(self, key: str) -> Any | None:
        self.get_calls.append(key)
        return self._store.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self.set_calls.append((key, value))
        self._store[key] = value


class FakeAsyncpgConn:
    """Duck-typed stand-in for an asyncpg connection."""

    def __init__(
        self,
        *,
        fetchrow_results: list[dict[str, Any] | None] | None = None,
        fetchval_results: list[Any] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._fetchrow_results = list(fetchrow_results or [])
        self._fetchval_results = list(fetchval_results or [])
        self._raises = raises

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if self._raises:
            raise self._raises
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if self._raises:
            raise self._raises
        return self._fetchval_results.pop(0) if self._fetchval_results else None


class FakeAsyncpgAcquire:
    def __init__(self, conn: FakeAsyncpgConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeAsyncpgConn:
        return self._conn

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeAsyncpgPool:
    """Duck-typed stand-in for `asyncpg.Pool`."""

    def __init__(self, conn: FakeAsyncpgConn | None = None) -> None:
        self.conn = conn or FakeAsyncpgConn()
        self.closed = False

    def acquire(self) -> FakeAsyncpgAcquire:
        return FakeAsyncpgAcquire(self.conn)

    async def close(self) -> None:
        self.closed = True
