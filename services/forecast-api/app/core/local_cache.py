"""Process-local, in-memory L1 cache -- sits in front of a Redis L2 cache
on a hot read path. A same-worker repeat request for an unexpired key
skips Redis's network round-trip *and* JSON re-serialization entirely,
at the cost of being per-process rather than shared across workers:
fine for a mostly-read, TTL-bounded cache where Redis remains the single
source of truth every worker still falls back to (and repopulates from)
on its own local miss.

Not distributed, not consistency-preserving across processes -- a caller
that mutates the underlying data (a cache warmer forcing a refresh) must
invalidate this cache explicitly alongside Redis; see
`app.service.cache_warmer`'s forecast warmer for that pairing.
"""

from __future__ import annotations

import time
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, maxsize: int = 256) -> None:
        self._maxsize = maxsize
        self._store: dict[str, tuple[float, T]] = {}

    def get(self, key: str) -> T | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: T, ttl_seconds: float) -> None:
        if key not in self._store and len(self._store) >= self._maxsize:
            # Evict the entry closest to expiry -- cheap stand-in for real
            # LRU that's good enough for the handful of distinct keys
            # (per-region/version) this is ever actually sized for.
            oldest_key = min(self._store, key=lambda k: self._store[k][0])
            del self._store[oldest_key]
        self._store[key] = (time.monotonic() + ttl_seconds, value)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
