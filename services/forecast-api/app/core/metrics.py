"""Prometheus metrics for forecast-api.

Server-side view of the forecast domain -- distinct from data-pipeline's
own `ecolens_forecast_requests_total`/`ecolens_forecast_latency_seconds`
(`services/data-pipeline/app/core/metrics.py`), which measure *that*
service's own calls into this one, not this service's own handling of
`GET /v1/forecast`. Named `..._predictions_total`/`..._prediction_latency_seconds`
(README.md's own example names, `ecolens_`-prefixed to match every other
service's convention) specifically so the two don't collide on the same
metric name under two different scrape jobs -- see
`services/observility/prometheus/rules/forecast.yml`'s header comment
for why both views matter (one measures the request from the caller's
side, the other from the model-serving side; they can diverge, e.g. if
network latency between data-pipeline and forecast-api grows).
"""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app import __version__

REGISTRY = CollectorRegistry()

# Standard Prometheus "info metric" pattern -- see data-pipeline's
# identical `build_info` for the full reasoning (services/observility's
# Observability Contract, why this beats a hardcoded scrape-config
# label).
build_info = Gauge(
    "ecolens_build_info",
    "Always 1 -- service identity via labels.",
    ["service", "version"],
    registry=REGISTRY,
)
build_info.labels(service="forecast-api", version=__version__).set(1)

forecast_predictions_total = Counter(
    "ecolens_forecast_predictions_total",
    "Forecast predictions served, by region and cache outcome.",
    ["region", "cache"],
    registry=REGISTRY,
)
forecast_prediction_latency_seconds = Histogram(
    "ecolens_forecast_prediction_latency_seconds",
    "GET /v1/forecast handler latency in seconds, by region. Includes "
    "cache hits (near-zero) and misses (a real model inference) alike -- "
    "filter by the cache label on forecast_predictions_total if you need "
    "them apart.",
    ["region"],
    registry=REGISTRY,
)
# `TODO.md` Observability Phase 1's "Custom Metrics Instrumentation" --
# "no drift-score or P10/P50/P90 prediction-error-rate metric exists
# anywhere" was called out explicitly. Set (not observed -- one drift
# check produces one current answer, not a distribution) by `ml/
# divergence.py`'s `check_drift` every time an incremental fine-tune
# actually runs one; stays at its last value between runs, which is the
# right semantics for "how far has the currently-deployed incremental
# path drifted from its last full retrain" (there's no "this instant"
# reading between checks the way there is for prediction latency).
forecast_drift_score = Gauge(
    "ecolens_forecast_drift_score",
    "ml/divergence.py's relative L2 weight-norm drift of the latest "
    "incremental fine-tune from its last full retrain, by model name.",
    ["model_name"],
    registry=REGISTRY,
)
# The other half of that same gap: a real P10/P50/P90 prediction-error
# distribution. Observed by `ml/forecast_reconciliation.py`'s
# `reconcile_pending_forecasts` once per reconciled forecast (real
# demand landed, compared against what was actually served) -- the same
# `error_pct` value that already decides `ForecastCircuitBreaker`
# success/failure, exposed as its own distribution rather than only the
# breaker's binary pass/fail view of it.
forecast_prediction_error_pct = Histogram(
    "ecolens_forecast_prediction_error_pct",
    "Reconciled forecast error, in percent of real demand, by model "
    "name and region.",
    ["model_name", "region"],
    # Matches this metric's real range: usually single digits (README.md's
    # own eval numbers), `_DEFAULT_ERROR_THRESHOLD_PCT`'s 15% is the
    # breaker's own trip point, and anything past 50% is already a
    # wildly-wrong prediction worth its own top bucket rather than more
    # resolution nobody needs up there.
    buckets=(1, 2, 5, 10, 15, 25, 50, float("inf")),
    registry=REGISTRY,
)


def metrics_as_text() -> bytes:
    """Render the registry in Prometheus text-exposition format."""
    return generate_latest(REGISTRY)
