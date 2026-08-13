"""Shared HTTP resilience helpers for the real (non-placeholder) historical
fetch loops in `ingest_aemo_nem.py`/`ingest_aemo_wem.py`/`ingest_bom.py`
(`TODO.md`'s "Robust HTTP Client" item: connection-pool limits + exponential
backoff retry).

`DEFAULT_LIMITS` bounds how many concurrent connections one client opens
against a single external host -- these loops already run one connection
at a time (sequential `await` per day/station, not `asyncio.gather`), so
this is a ceiling against accidental future concurrency, not a live
bottleneck fix today.

`fetch_with_retry` wraps one already-in-flight-loop unit (one archive
day, one weather station) with jittered exponential backoff, same style
`duckdb_staging.py`'s `_connect_rw_with_retry` already uses elsewhere in
this codebase. Retries on `httpx.TransportError` (connection reset,
DNS failure, timeout) and 5xx `HTTPStatusError` -- both plausibly
transient. Does **not** retry a 4xx (a malformed request retrying
identically will just fail identically) or any other exception (a
parsing bug retrying won't fix itself either) -- those still propagate
to the caller's existing per-unit try/except, which logs and moves on
to the next day/station, same "one bad unit shouldn't sink the batch"
pattern already established.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from app.core.logging import get_logger
from app.core.metrics import http_poll_duration_seconds

log = get_logger(__name__)

T = TypeVar("T")

#: Per-client connection pool ceiling -- passed to `httpx.AsyncClient(limits=...)`.
DEFAULT_LIMITS = httpx.Limits(max_connections=10, max_keepalive_connections=5)

_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BASE_DELAY_SECONDS = 1.0


async def fetch_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    source: str,
    log_event: str,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_delay_seconds: float = _DEFAULT_BASE_DELAY_SECONDS,
    **log_fields: object,
) -> T:
    """Calls `fn()`, retrying up to `max_attempts` times (jittered
    exponential backoff: `base_delay_seconds * 2**attempt`, plus up to
    0.25s jitter) on a transient `httpx` failure. Re-raises the last
    error if every attempt fails -- the caller's own per-unit try/except
    (already present in every one of this function's callers) is what
    actually turns that into "log and skip this day/station", not this
    function.

    `source`: a `registry.IngestSource.source` value (`"aemo_nem"`,
    `"aemo_wem"`, `"bom"`) -- labels `core/metrics.py`'s
    `http_poll_duration_seconds`, timed around the whole call including
    any retries/backoff below, not just whichever attempt happened to
    succeed.
    """
    started = time.monotonic()
    try:
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return await fn()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise
                last_error = exc
            except httpx.TransportError as exc:
                last_error = exc

            if attempt < max_attempts - 1:
                delay = base_delay_seconds * (2**attempt) + random.uniform(0, 0.25)
                log.warning(
                    log_event,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    sleep_seconds=round(delay, 2),
                    error=str(last_error),
                    **log_fields,
                )
                await asyncio.sleep(delay)

        assert last_error is not None  # noqa: S101 -- loop above always sets it before falling through
        raise last_error
    finally:
        http_poll_duration_seconds.labels(source=source).observe(
            time.monotonic() - started
        )
