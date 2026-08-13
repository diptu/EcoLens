"""Adaptive conformal-interval scaling (`TODO.md` Forecasting Phase 4's
"Build automated safety checks to widen or tighten uncertainty bounds if
error rates drift out of bounds") -- the half of that checklist item
`ForecastCircuitBreaker`/`forecast_reconciliation.py` don't cover.
The breaker swaps the *whole model* out for a baseline on a sustained,
large miscalibration; this handles the far more common case of a model
that's still the right one to serve, just not perfectly calibrated at
conformal-fit time anymore -- e.g. a shift in demand volatility since
`ml/train.py`'s calibration split was carved out, well short of what
would actually trip the breaker.

Real Adaptive Conformal Inference (Gibbs & Candès, 2021: "Adaptive
Conformal Inference Under Distribution Shift"), simplified to one scalar
multiplier per `(model_name, region)` rather than adapting the
underlying miscoverage level directly. Every reconciled forecast either
did or didn't contain the real value inside the interval this service
actually served -- the *already-scaled* one, not the raw conformal
calibration's own width, since this has to adapt against its own output
to ever converge. A miss nudges the scale up (wider next time); a hit
nudges it down toward 1.0 -- `target_alpha` misses are the *expected*
outcome at the calibration's intended width (a `target_alpha` of 0.2
means a real fifth of hits should look like misses), not zero, so a
perfect no-misses streak still relaxes the scale back toward 1.0 rather
than driving it to 0.

Persisted as a plain Redis string with no TTL, deliberately -- unlike
`forecast_reconciliation.py`'s per-forecast served/pending hashes (a
transient "did we get this one right" QA signal), this scale *is* the
adaptation: letting it silently expire and reset to 1.0 mid-drift would
undo exactly the correction this module exists to make.
"""

from __future__ import annotations

from redis.asyncio import Redis

#: No adaptation yet applied -- conformal calibration's own width, unscaled.
DEFAULT_SCALE = 1.0
#: Clamped so a long lucky streak can't collapse the interval toward
#: zero width, and a long unlucky one can't blow it out to something
#: useless -- generous enough (2x either direction of the 1.0 default)
#: that real, sustained drift still visibly moves the number long before
#: hitting either wall.
MIN_SCALE = 0.5
MAX_SCALE = 3.0
#: Small on purpose -- this adapts over many reconciled forecasts (the
#: reconciliation sweep's own cadence, `Settings.
#: forecast_reconciliation_interval_seconds`), not from a single miss.
#: `1 / step_size` = 50 reconciled forecasts to move the scale by a full
#: 1.0 if every single one missed, which is already breaker-tripping
#: territory long before that.
DEFAULT_STEP_SIZE = 0.02

_SCALE_KEY_PREFIX = "forecast_calibration_scale"


def calibration_scale_key(model_name: str, region: str) -> str:
    """The one place `(model_name, region)` becomes this scale's Redis
    key -- `forecast_reconciliation.py` and `api/v1/forecast/routes.py`
    must agree on it, so it's not duplicated as a string-format in both
    places."""
    return f"{_SCALE_KEY_PREFIX}:{model_name}:{region}"


async def get_calibration_scale(redis: Redis, model_name: str, region: str) -> float:
    """`DEFAULT_SCALE` (unscaled) if this `(model_name, region)` has
    never been reconciled yet -- a real, expected state for a freshly
    deployed model version, not an error."""
    raw = await redis.get(calibration_scale_key(model_name, region))
    if raw is None:
        return DEFAULT_SCALE
    return float(raw.decode() if isinstance(raw, bytes) else raw)


async def update_calibration_scale(
    redis: Redis,
    *,
    model_name: str,
    region: str,
    covered: bool,
    target_alpha: float,
    step_size: float = DEFAULT_STEP_SIZE,
) -> float:
    """One Adaptive-Conformal-Inference-style update step, called once
    per reconciled forecast (`forecast_reconciliation.
    reconcile_pending_forecasts`) -- `covered`: whether the real demand
    value actually fell inside the interval this service served for it.
    Returns (and persists) the new scale."""
    current = await get_calibration_scale(redis, model_name, region)
    miss = 0.0 if covered else 1.0
    updated = current + step_size * (miss - target_alpha)
    updated = min(max(updated, MIN_SCALE), MAX_SCALE)
    await redis.set(calibration_scale_key(model_name, region), str(updated))
    return updated
