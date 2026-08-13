"""Closes `app.service.ml.forecast_breaker`'s own documented gap
(`todo-model-training.md` Phase 6 / root `TODO.md`'s Forecasting Phase 4
"Self-Correction & Fallback Mechanism"): that module's circuit-breaker
state machine was complete and tested in isolation, but nothing actually
drove it -- no job persisted what was served, nothing reconciled it
against real demand once it landed, and `GET /v1/forecast` never checked
`breaker.state` before serving. This module is the "persist + reconcile"
half; `api/v1/forecast/routes.py` is the "check state + fall back" half.

**Design**: `record_served_forecast` logs only the *shortest-horizon*
point of each real (non-fallback) forecast -- the soonest one to become
reconcilable, and the cheapest to store (one point per request, not the
full `horizon`-length array). Stored in Redis, not Postgres: this is a
transient "did we get this one right" signal feeding a breaker that
already lives in Redis, not a permanent audit record (`meta._ingest_log`-
style durability isn't the point here). One hash per `(model_name,
region)`, field = target timestamp, so `reconcile_pending_forecasts` can
sweep all pending entries for a given breaker in one `HGETALL` — a
sorted set keyed by score=target_ts would support range queries better
at a much larger scale, but this service serves a handful of regions,
not thousands, so the simpler structure is the right tradeoff today.

`reconcile_pending_forecasts` is meant to run periodically
(`watch_and_reconcile`, mirroring `ml/registry.py`'s `ModelRegistry.
watch` background-task pattern) -- not synchronously in any request
path. A forecast target only becomes reconcilable once real demand for
that exact timestamp has landed in `raw_marts.fct_energy_demand`, which
can be hours after it was served; there is no request-shaped moment to
check that.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.metrics import forecast_prediction_error_pct
from app.service.ml.adaptive_calibration import update_calibration_scale
from app.service.ml.data import MARTS_SCHEMA
from app.service.ml.forecast_breaker import ForecastCircuitBreaker

log = get_logger(__name__)

_SERVED_KEY_PREFIX = "forecast_served"
#: Generous relative to any region's real horizon (WEM's 24h is the
#: longest) -- covers the forecast's own reach plus real time for the
#: warehouse to actually land the corresponding demand row before this
#: entry would otherwise expire un-reconciled.
_DEFAULT_TTL_SECONDS = 172_800  # 48h
#: A forecast this far off from what actually happened counts as a
#: breaker failure -- 15% is well outside this model's normal MAPE
#: (single digits, per `README.md`'s own eval numbers), so this only
#: trips on a real, meaningfully-wrong prediction, not routine noise.
_DEFAULT_ERROR_THRESHOLD_PCT = 15.0
#: `adaptive_calibration.py`'s target miscoverage -- matches `Settings.
#: conformal_alpha`'s own default (0.2 -> an 80% P10-P90 interval), so a
#: caller that doesn't override this still adapts toward the same
#: coverage the conformal calibration was originally fit to hit.
_DEFAULT_TARGET_ALPHA = 0.2


def breaker_name(model_name: str, region: str) -> str:
    """The one place `(model_name, region)` becomes a `ForecastCircuitBreaker`
    name -- `api/v1/forecast/routes.py` and this module must agree on it,
    so it's not duplicated as a string-format in both places."""
    return f"{model_name}:{region}"


def _served_key(model_name: str, region: str) -> str:
    return f"{_SERVED_KEY_PREFIX}:{breaker_name(model_name, region)}"


async def record_served_forecast(
    redis: Redis,
    *,
    model_name: str,
    region: str,
    target_ts: datetime,
    p50_mw: float,
    p10_mw: float,
    p90_mw: float,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> None:
    """Records one real (non-fallback) prediction for later reconciliation.
    A second call for the same `(model_name, region, target_ts)` (e.g. a
    cache-miss re-serving close to the same origin) simply overwrites --
    reconciliation only ever cares about the most recently promised
    value for that timestamp, not a history of every prediction ever
    made for it.

    `p10_mw`/`p90_mw`: the interval actually served (i.e. already scaled
    by `adaptive_calibration.py`'s current multiplier, not the raw
    conformal-calibration width) -- `reconcile_pending_forecasts` needs
    these to know whether the real value landed inside what was actually
    promised, which is what that module's own adaptation loop has to
    check itself against to ever converge."""
    key = _served_key(model_name, region)
    hash_field = target_ts.astimezone(UTC).isoformat()
    value = json.dumps(
        {
            "p50_mw": p50_mw,
            "p10_mw": p10_mw,
            "p90_mw": p90_mw,
            "served_at": datetime.now(UTC).isoformat(),
        }
    )
    await redis.hset(key, hash_field, value)
    await redis.expire(key, ttl_seconds)


@dataclass
class ReconciliationResult:
    reconciled: int = 0
    still_pending: int = 0
    successes: int = 0
    failures: int = 0
    errors_pct: list[float] = field(default_factory=list)
    #: How many reconciled entries actually had a `p10_mw`/`p90_mw` to
    #: check coverage against and drive `adaptive_calibration.py` with --
    #: always equal to `reconciled` for anything served after that
    #: module existed; only less than it for pre-existing Redis entries
    #: from before this field was added (harmless: those just skip the
    #: coverage update, not the breaker one).
    coverage_checked: int = 0
    covered: int = 0


async def _real_demand_mw(
    db: AsyncSession, region: str, ts: datetime
) -> float | None:
    result = await db.execute(
        text(
            # nosec B608 -- MARTS_SCHEMA is a fixed module constant, not user input
            f"SELECT demand_mw FROM {MARTS_SCHEMA}.fct_energy_demand "  # nosec B608
            "WHERE region = :region AND ts = :ts"
        ),
        {"region": region, "ts": ts},
    )
    row = result.first()
    if row is None or row[0] is None:
        return None
    return float(row[0])


async def reconcile_pending_forecasts(
    redis: Redis,
    db: AsyncSession,
    *,
    model_name: str,
    region: str,
    error_threshold_pct: float = _DEFAULT_ERROR_THRESHOLD_PCT,
    target_alpha: float = _DEFAULT_TARGET_ALPHA,
    now: datetime | None = None,
) -> ReconciliationResult:
    """Sweeps every served-forecast entry for `(model_name, region)`
    whose `target_ts` has passed, looks up the real `demand_mw` for that
    exact timestamp, and drives the matching `ForecastCircuitBreaker`
    with the outcome. An entry with no matching real row yet (the
    warehouse hasn't landed it -- forecast target still in the future
    from the mart's own perspective, or a real data gap) is left alone,
    to be retried on the next pass; it only ever gets removed once
    reconciled (or once its own Redis TTL expires, for a target that
    genuinely never lands).
    """
    now = now or datetime.now(UTC)
    key = _served_key(model_name, region)
    entries = await redis.hgetall(key)
    result = ReconciliationResult()
    if not entries:
        return result

    breaker = ForecastCircuitBreaker(breaker_name(model_name, region), redis)

    for hash_field, raw_value in entries.items():
        field_str = hash_field.decode() if isinstance(hash_field, bytes) else hash_field
        value_str = raw_value.decode() if isinstance(raw_value, bytes) else raw_value
        target_ts = datetime.fromisoformat(field_str)
        if target_ts > now:
            result.still_pending += 1
            continue

        payload = json.loads(value_str)
        predicted_p50 = float(payload["p50_mw"])

        actual = await _real_demand_mw(db, region, target_ts)
        if actual is None:
            # Real data for this timestamp hasn't landed yet -- not
            # reconcilable this pass, but also not stale enough to give
            # up on (the hash's own TTL is the real backstop for "never
            # landed at all").
            result.still_pending += 1
            continue

        error_pct = (
            abs(predicted_p50 - actual) / abs(actual) * 100 if actual != 0 else 0.0
        )
        forecast_prediction_error_pct.labels(
            model_name=model_name, region=region
        ).observe(error_pct)
        if error_pct > error_threshold_pct:
            await breaker.record_failure()
            result.failures += 1
        else:
            await breaker.record_success()
            result.successes += 1
        result.errors_pct.append(error_pct)
        result.reconciled += 1

        # `adaptive_calibration.py`'s update -- a distinct, separate
        # signal from the breaker above: this checks whether the real
        # value fell inside the *interval* actually served, not whether
        # the point estimate was close. Guarded on both fields being
        # present so a Redis entry served before this field existed
        # (this deploy's own rollout window) doesn't raise instead of
        # just skipping the adaptation for that one entry.
        p10_mw = payload.get("p10_mw")
        p90_mw = payload.get("p90_mw")
        if p10_mw is not None and p90_mw is not None:
            covered = float(p10_mw) <= actual <= float(p90_mw)
            await update_calibration_scale(
                redis,
                model_name=model_name,
                region=region,
                covered=covered,
                target_alpha=target_alpha,
            )
            result.coverage_checked += 1
            if covered:
                result.covered += 1

        await redis.hdel(key, hash_field)

    if result.reconciled:
        log.info(
            "forecast.reconciliation_completed",
            model_name=model_name,
            region=region,
            reconciled=result.reconciled,
            successes=result.successes,
            failures=result.failures,
            still_pending=result.still_pending,
            coverage_checked=result.coverage_checked,
            covered=result.covered,
        )
    return result


async def watch_and_reconcile(
    redis: Redis,
    db_session_factory,
    *,
    model_names_and_regions: list[tuple[str, str]],
    interval_seconds: float,
    error_threshold_pct: float = _DEFAULT_ERROR_THRESHOLD_PCT,
    target_alpha: float = _DEFAULT_TARGET_ALPHA,
) -> None:
    """Runs `reconcile_pending_forecasts` forever, once per
    `interval_seconds`, for every `(model_name, region)` pair this
    service actually serves -- `app.main`'s lifespan background task,
    same "loop forever, log and keep going on a single-pass failure"
    shape `ml.registry.ModelRegistry.watch` already establishes (a
    broken reconciliation pass must never crash the whole service, and
    must never stop future passes from trying again)."""
    while True:
        for model_name, region in model_names_and_regions:
            try:
                async with db_session_factory() as db:
                    await reconcile_pending_forecasts(
                        redis,
                        db,
                        model_name=model_name,
                        region=region,
                        error_threshold_pct=error_threshold_pct,
                        target_alpha=target_alpha,
                    )
            except Exception as exc:  # noqa: BLE001 - one bad pass must not stop future ones
                log.error(
                    "forecast.reconciliation_pass_failed",
                    model_name=model_name,
                    region=region,
                    error=str(exc),
                )
        await asyncio.sleep(interval_seconds)
