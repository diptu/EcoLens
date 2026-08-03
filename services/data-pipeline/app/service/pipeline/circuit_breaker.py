"""Redis-backed circuit breaker for external API calls.

State lives in Redis rather than process memory, so a breaker tripped by
one process (an API worker, a cron-triggered CLI invocation) is honoured
by every other process talking to the same Redis instance.

State machine: `closed` -> `open` (>= `failure_threshold` consecutive
failures) -> `half_open` (once `reset_timeout` seconds have elapsed) ->
`closed` (the half-open trial call succeeds) or back to `open` (it fails).

Concurrent half-open trials are not serialised with a distributed lock —
if several callers race in during the half-open window, more than one
trial call may go through. That's an accepted simplification here; a
stricter implementation would add a Redis-based lock around the trial.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, TypeVar

from redis.asyncio import Redis

_T = TypeVar("_T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# Back-compat module-level aliases (str-enum members compare equal to
# their raw string value, so these work as plain strings too).
CLOSED = CircuitState.CLOSED
OPEN = CircuitState.OPEN
HALF_OPEN = CircuitState.HALF_OPEN


class CircuitOpenError(Exception):
    """Raised by `CircuitBreaker.call()` while the breaker is open."""


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        redis: Redis,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._redis = redis
        self._failures_key = f"circuit_breaker:{name}:failures"
        self._opened_at_key = f"circuit_breaker:{name}:opened_at"

    @property
    def state(self) -> Awaitable[CircuitState]:
        """Current state, derived from Redis — never cached locally.

        A property returning an *unawaited* coroutine, so callers write
        `await breaker.state` (matches `CircuitState`'s enum-like feel)
        rather than `await breaker.state()`.
        """
        return self._compute_state()

    async def _compute_state(self) -> CircuitState:
        opened_at = await self._redis.get(self._opened_at_key)
        if opened_at is None:
            return CircuitState.CLOSED
        if time.time() - float(opened_at) >= self.reset_timeout:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    async def call(
        self, fn: Callable[..., Awaitable[_T]], *args: Any, **kwargs: Any
    ) -> _T:
        """Run `fn(*args, **kwargs)` unless the breaker is open.

        `fn` is a callable returning an awaitable rather than an
        already-created coroutine, so nothing runs — and no "coroutine
        was never awaited" warning fires — when the call is rejected.
        """
        if await self.state == CircuitState.OPEN:
            raise CircuitOpenError(f"circuit '{self.name}' is open")

        try:
            result = await fn(*args, **kwargs)
        except Exception:
            await self._record_failure()
            raise
        else:
            await self._record_success()
            return result

    async def _record_failure(self) -> None:
        failures = await self._redis.incr(self._failures_key)
        if failures >= self.failure_threshold:
            await self._redis.set(self._opened_at_key, time.time())

    async def _record_success(self) -> None:
        await self._redis.delete(self._failures_key, self._opened_at_key)
