"""Shared pytest fixtures/test doubles for the data-pipeline test suite."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class FakeConnectionPool:
    """Duck-typed stand-in for `ecolens.warehouse.api.db.ConnectionPool`.

    Used by query-helper and route tests so they never need a real
    PostgreSQL connection. Records every call for assertions and
    returns whatever canned result was configured.
    """

    def __init__(
        self,
        *,
        fetch_result: list[dict[str, Any]] | None = None,
        fetchrow_result: dict[str, Any] | None = None,
        fetchval_result: Any = None,
        connected: bool = True,
    ) -> None:
        self.is_connected = connected
        self._fetch_result = fetch_result if fetch_result is not None else []
        self._fetchrow_result = fetchrow_result
        self._fetchval_result = fetchval_result
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append(("fetch", query, args))
        return self._fetch_result

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.calls.append(("fetchrow", query, args))
        return self._fetchrow_result

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.calls.append(("fetchval", query, args))
        return self._fetchval_result


class FakeAsyncpgConn:
    """Duck-typed stand-in for an asyncpg connection.

    `fetchrow`/`fetchval` results are consumed in call order (a queue)
    so a test can supply one canned response per expected call, in the
    order the code under test is known to issue them (e.g. one row per
    table in a fixed iteration). `execute` just records what it was
    asked to run.
    """

    def __init__(
        self,
        *,
        fetchrow_results: list[dict[str, Any] | None] | None = None,
        fetchval_results: list[Any] | None = None,
        fetch_result: list[dict[str, Any]] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._fetchrow_results = list(fetchrow_results or [])
        self._fetchval_results = list(fetchval_results or [])
        self._fetch_result = fetch_result if fetch_result is not None else []
        self._raises = raises
        self.executed: list[str] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if self._raises:
            raise self._raises
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if self._raises:
            raise self._raises
        return self._fetchval_results.pop(0) if self._fetchval_results else None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if self._raises:
            raise self._raises
        return self._fetch_result

    async def execute(self, query: str, *args: Any) -> None:
        if self._raises:
            raise self._raises
        self.executed.append(query)


class FakeAsyncpgAcquire:
    """`pool.acquire()` returns this; `async with` yields the fake conn."""

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


class FakeMongoCollection:
    """Duck-typed stand-in for a pymongo Collection."""

    def __init__(
        self,
        *,
        doc: dict[str, Any] | None = None,
        delete_count: int = 0,
    ) -> None:
        self._doc = doc
        self._delete_count = delete_count
        self.delete_calls: list[Any] = []

    def find_one(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return self._doc

    def delete_many(self, filter: Any) -> SimpleNamespace:  # noqa: A002
        self.delete_calls.append(filter)
        return SimpleNamespace(deleted_count=self._delete_count)


class FakeMongoClient:
    """Duck-typed stand-in for `pymongo.MongoClient`.

    `collections` maps collection name -> FakeMongoCollection; any
    name not in the map gets an empty default collection (find_one ->
    None, delete_many -> 0 deleted) rather than a KeyError.
    """

    def __init__(
        self,
        *args: Any,
        collections: dict[str, FakeMongoCollection] | None = None,
        ping_raises: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        self._collections = collections or {}
        self._ping_raises = ping_raises
        self.closed = False
        self.admin = SimpleNamespace(command=self._command)

    def _command(self, *args: Any, **kwargs: Any) -> dict[str, int]:
        if self._ping_raises:
            raise self._ping_raises
        return {"ok": 1}

    def __getitem__(self, _db_name: str) -> "_FakeMongoDb":
        return _FakeMongoDb(self._collections)

    def close(self) -> None:
        self.closed = True


class _FakeMongoDb:
    def __init__(self, collections: dict[str, FakeMongoCollection]) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> FakeMongoCollection:
        return self._collections.setdefault(name, FakeMongoCollection())


class FakePgConnection:
    """Duck-typed stand-in for a psycopg2 connection."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises
        self.autocommit_set = False
        self.closed = False
        self.executed: list[str] = []

    def set_session(self, *, autocommit: bool = False) -> None:
        self.autocommit_set = autocommit

    def cursor(self) -> "_FakePgCursor":
        return _FakePgCursor(self)

    def close(self) -> None:
        self.closed = True


class _FakePgCursor:
    def __init__(self, conn: FakePgConnection) -> None:
        self._conn = conn

    def execute(self, query: str, *args: Any) -> None:
        if self._conn._raises:
            raise self._conn._raises
        self._conn.executed.append(query)

    def close(self) -> None:
        pass


class FakeRedis:
    """In-memory duck-typed stand-in for `redis.asyncio.Redis`.

    Only implements the handful of commands `CircuitBreaker` actually
    uses (get/set/incr/expire/delete) -- enough to test breaker
    open/close transitions without a live Redis server.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: Any, *, ex: int | None = None) -> None:
        # `ex` (TTL) is accepted for interface parity but not enforced --
        # tests that care about expiry drive it via monkeypatched `time.time()`.
        self._store[key] = str(value)

    async def incr(self, key: str) -> int:
        value = int(self._store.get(key, "0")) + 1
        self._store[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> None:
        pass

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(key, None)
