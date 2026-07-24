"""Prometheus metrics for forecast-api (ECO-T02).

Multiprocess-safe: Gunicorn (`gunicorn_conf.py`, ECO-F01) runs this app
as several worker processes by default, and `prometheus_client`'s
default global registry is per-process -- a single `/metrics` scrape
would only see whichever one worker happened to handle it, silently
under-reporting every other worker's traffic. Multiprocess mode fixes
this: each worker writes its counters/histograms to files in
`PROMETHEUS_MULTIPROC_DIR` (set up by `gunicorn_conf.py` before workers
fork), and `render_metrics()` aggregates across all of them.

Under plain `uvicorn --reload` (dev; `PROMETHEUS_MULTIPROC_DIR` unset),
this falls back to the default single-process registry -- still
correct, since there's only one process to report on.

Latency, cache hit-rate, and model-reload success/failure (ECO-T02's
three asks) are all wired up here -- the last one only became possible
once ECO-F04's reload loop existed to produce real events; see
`forecasting/reload.py`'s `record_reload_result` calls.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

REQUEST_LATENCY = Histogram(
    "forecast_api_request_duration_seconds",
    "Forecast request latency in seconds, from route entry to response.",
    ["region"],
)

CACHE_REQUESTS = Counter(
    "forecast_api_cache_requests_total",
    "Cache lookups on the forecast route by result.",
    ["result"],  # "hit" | "miss" | "disabled"
)

MODEL_RELOADS = Counter(
    "forecast_api_model_reload_total",
    "Model hot-reload attempts (ECO-F04) by outcome.",
    ["result"],  # "swapped" | "unchanged" | "failed"
)


@contextmanager
def time_forecast_request(region: str) -> Iterator[None]:
    """Times the wrapped block and records it under `region`, even on error.

    Wraps the whole route body (cache check through response), not just
    the DB call -- "how long did this request take" is the useful
    number, and it should include a cache hit's near-zero latency too
    so the histogram reflects real client-observed timing.
    """
    with REQUEST_LATENCY.labels(region=region).time():
        yield


def record_cache_result(*, enabled: bool, hit: bool) -> None:
    """Call once per forecast request after the cache lookup."""
    if not enabled:
        CACHE_REQUESTS.labels(result="disabled").inc()
    elif hit:
        CACHE_REQUESTS.labels(result="hit").inc()
    else:
        CACHE_REQUESTS.labels(result="miss").inc()


def record_reload_result(result: str) -> None:
    """Call once per `ModelReloader.reload_once()` -- `result` is one of
    `"swapped"` (new version passed its sanity check and is now serving),
    `"unchanged"` (nothing new, or already serving the latest version),
    or `"failed"` (load error or sanity-check rejection, ECO-F08).
    """
    MODEL_RELOADS.labels(result=result).inc()


def render_metrics() -> tuple[bytes, str]:
    """Renders the current metrics. Returns `(body, content_type)` for a raw `Response`."""
    if "PROMETHEUS_MULTIPROC_DIR" in os.environ:
        # Imported lazily: this submodule assumes the multiprocess dir
        # already exists, which is only true once gunicorn_conf.py has
        # set it up -- importing it unconditionally at module load time
        # would break the plain single-process (dev) path.
        from prometheus_client import multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        from prometheus_client import REGISTRY as registry

    return generate_latest(registry), CONTENT_TYPE_LATEST


__all__ = [
    "REQUEST_LATENCY",
    "CACHE_REQUESTS",
    "MODEL_RELOADS",
    "time_forecast_request",
    "record_cache_result",
    "record_reload_result",
    "render_metrics",
]
