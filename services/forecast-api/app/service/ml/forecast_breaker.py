"""Redis-backed circuit breaker for forecast *quality*
(`todo-model-training.md` Phase 6) — same closed → open → half_open
state machine as data-pipeline's `pipeline/circuit_breaker.py` (external-
API-availability breaker), adapted here for a genuinely different trip
condition. `README.md`'s service-boundary rule ("don't import across
services") means this is forecast-api's own copy, not a shared import —
same real design, real reason to duplicate rather than share.

**Why this can't just reuse `CircuitBreaker.call()`'s pattern**: the
data-pipeline breaker trips on a wrapped call *raising* — a natural fit
for "is this upstream API reachable right now". A forecast-serving
breaker trips on *realized* forecast error (once real demand lands for a
timestamp this service already forecasted) being too large — there's no
single fallible call to wrap; the failure/success signal comes from a
separate, later reconciliation step (comparing `raw_marts.
fct_energy_demand.demand_mw` against whatever was served at that
horizon). `record_success`/`record_failure` are exposed as public
methods for exactly that caller to drive directly, instead of `call()`
wrapping an awaitable.

**Real, honest status**: this state machine is complete and tested in
isolation. The *trip condition* itself — a job that persists what was
actually served (nothing today logs "this forecast was served for this
timestamp at this horizon" anywhere) and reconciles it against real
demand once it lands — and the `GET /v1/forecast` route's own fallback
branch (serve the seasonal-naive baseline when open, report `served_by`
honestly) are real, deliberately out of scope for this pass — see
`todo-model-training.md` Phase 6 for that work tracked openly, not
silently implied as already wired in.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable
from enum import Enum

from redis.asyncio import Redis


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


CLOSED = CircuitState.CLOSED
OPEN = CircuitState.OPEN
HALF_OPEN = CircuitState.HALF_OPEN


class ForecastCircuitBreaker:
    """One breaker per `(model_name, region)` (`name`, e.g.
    `"lstm_demand:NSW1"`) -- a model can be healthy for one region's
    demand pattern and unhealthy for another's, so state is tracked per
    pair, not globally per model.
    """

    def __init__(
        self,
        name: str,
        redis: Redis,
        failure_threshold: int = 5,
        reset_timeout: float = 3600.0,
    ) -> None:
        """`reset_timeout` defaults to 1 hour, not
        `pipeline.circuit_breaker`'s 60s default -- a forecast-quality
        trip reflects a real model/data problem that won't self-resolve
        on the timescale an unreachable HTTP endpoint might; trialing
        again after 60s would almost certainly fail the same way and
        just flap the breaker."""
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._redis = redis
        self._failures_key = f"forecast_circuit_breaker:{name}:failures"
        self._opened_at_key = f"forecast_circuit_breaker:{name}:opened_at"

    @property
    def state(self) -> Awaitable[CircuitState]:
        """Current state, derived from Redis -- never cached locally.
        Returns an *unawaited* coroutine (see `pipeline.circuit_breaker.
        CircuitBreaker`'s identical pattern) so callers write `await
        breaker.state`."""
        return self._compute_state()

    async def _compute_state(self) -> CircuitState:
        opened_at = await self._redis.get(self._opened_at_key)
        if opened_at is None:
            return CircuitState.CLOSED
        if time.time() - float(opened_at) >= self.reset_timeout:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    async def record_success(self) -> None:
        """Call after confirming a recent realized forecast was
        accurate — in `closed`, resets the failure count (a real recent
        good result shouldn't let older failures still count toward the
        threshold); in `half_open`, this is the real recovery trial
        succeeding, closing the breaker again."""
        await self._redis.delete(self._failures_key, self._opened_at_key)

    async def record_failure(self) -> None:
        """Call after confirming a recent realized forecast error
        exceeded the real trip threshold. In `half_open`, any single
        failure re-opens immediately (no "give it a few more tries" —
        the half-open trial itself already *is* the second chance)."""
        state = await self._compute_state()
        if state == CircuitState.HALF_OPEN:
            await self._redis.set(self._opened_at_key, time.time())
            return
        failures = await self._redis.incr(self._failures_key)
        if failures >= self.failure_threshold:
            await self._redis.set(self._opened_at_key, time.time())
