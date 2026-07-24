"""Shared network-safety primitives for the ingestion layer.

Two independent pieces, both driven by the `ingest_*` tunables already
declared on `MongoSettings` (previously unused -- every source hand-rolled
its own retry loop, if it had one at all):

  - `retry_with_backoff()` -- exponential backoff with jitter, no
    external dependency. Safe to wrap around any single-shot async
    call.
  - `CircuitBreaker` -- per-source open/closed state backed by Redis
    (see INGESTION.md's pipeline diagram, step 3: "Redis circuit
    breaker") so the breaker is shared across concurrent ingestion
    workers/cron invocations, not just within one process. Threshold =
    consecutive failures before it opens; timeout = how long it stays
    open before allowing a half-open trial call.

A `CircuitBreaker` is optional at every call site: consumers accept it
as `circuit_breaker: CircuitBreaker | None = None` and skip the check
entirely when it's None, so existing zero-arg client construction (and
every test that relies on it) keeps working without a live Redis
instance.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, TypeVar

from ecolens.shared.observability.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from ecolens.ingestion.storage.settings import MongoSettings

log = get_logger(__name__)

T = TypeVar("T")


class CircuitBreakerOpen(Exception):
    """Raised by `CircuitBreaker.before_call()` while the breaker is open."""

    def __init__(self, source: str, retry_after_seconds: float) -> None:
        self.source = source
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"circuit breaker open for {source!r}, retry after "
            f"{retry_after_seconds:.0f}s"
        )


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    backoff_base: float,
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> T:
    """Retry `fn()` up to `max_retries` times.

    Delay before attempt N+1 is `backoff_base ** N` seconds, +/- 20%
    jitter (avoids every retrying caller waking up in lockstep).
    Re-raises the last exception once every attempt has failed.

    `max_retries` is a total-attempt count (matches the existing
    per-source convention in aemo_nem/client.py and bom/client.py, not
    "retries after the first"). `MongoSettings.ingest_max_retries`
    allows 0 -- treated as "try once, don't retry" rather than raising.
    """
    if max_retries < 1:
        return await fn()
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below once exhausted
            last_exc = exc
        if attempt < max_retries:
            delay = backoff_base**attempt * random.uniform(0.8, 1.2)  # nosec B311 - jitter, not crypto
            if on_retry is not None:
                on_retry(attempt, last_exc, delay)
            await asyncio.sleep(delay)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(
        "retry_with_backoff: unreachable -- loop always runs >=1 time"
    )  # pragma: no cover


class CircuitBreaker:
    """Redis-backed circuit breaker, one instance per source.

    States: closed (normal) -> open (failing fast, `before_call` raises)
    -> half_open (the first call after `timeout_seconds` is let through)
    -> closed again on success, or back to open on failure.
    """

    def __init__(
        self,
        source: str,
        redis: "Redis",
        *,
        settings: "MongoSettings | None" = None,
    ) -> None:
        from ecolens.ingestion.storage.settings import get_mongo_settings

        self.source = source
        self.redis = redis
        settings = settings or get_mongo_settings()
        self.threshold = settings.ingest_circuit_breaker_threshold
        self.timeout_seconds = settings.ingest_circuit_breaker_timeout_seconds
        self._failures_key = f"circuit_breaker:{source}:failures"
        self._opened_at_key = f"circuit_breaker:{source}:opened_at"

    async def before_call(self) -> None:
        """Raise `CircuitBreakerOpen` if the breaker is currently open."""
        opened_at = await self.redis.get(self._opened_at_key)
        if opened_at is None:
            return
        remaining = self.timeout_seconds - (time.time() - float(opened_at))
        if remaining <= 0:
            # Timeout elapsed: move to half-open by clearing the "open"
            # marker (the failure count stays until a call succeeds, so
            # one more failure re-opens it immediately).
            await self.redis.delete(self._opened_at_key)
            return
        raise CircuitBreakerOpen(self.source, remaining)

    async def record_success(self) -> None:
        await self.redis.delete(self._failures_key, self._opened_at_key)

    async def record_failure(self) -> None:
        failures = await self.redis.incr(self._failures_key)
        await self.redis.expire(self._failures_key, self.timeout_seconds * 2)
        if failures >= self.threshold:
            await self.redis.set(
                self._opened_at_key, time.time(), ex=self.timeout_seconds
            )
            log.warning(
                "circuit_breaker.opened",
                source=self.source,
                failures=failures,
                timeout_seconds=self.timeout_seconds,
            )

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Run `fn()` guarded by this breaker.

        Raises `CircuitBreakerOpen` (without calling `fn`) if open;
        otherwise records success/failure based on the outcome.
        """
        await self.before_call()
        try:
            result = await fn()
        except Exception:
            await self.record_failure()
            raise
        else:
            await self.record_success()
            return result


__all__ = ["CircuitBreaker", "CircuitBreakerOpen", "retry_with_backoff"]
