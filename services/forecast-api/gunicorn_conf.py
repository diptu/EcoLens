"""Gunicorn config for production: Gunicorn as the process manager,
`UvicornWorker` as the actual ASGI worker (ECO-F01).

Plain `uvicorn --reload` (see `make api` / README's "Run" section) is
fine for local dev — one process, auto-reload, easy to attach a
debugger to. It's the wrong shape for production: no worker
supervision, no zero-downtime restarts, one process pinned to one CPU
core. Gunicorn adds exactly that supervision layer on top of the same
ASGI app; the app code (`app.py`, `routes.py`, ...) doesn't change at
all between the two.

`uvicorn.workers.UvicornWorker` was removed from the `uvicorn` package
itself (it now only ships the standalone server); the replacement is
the separate `uvicorn-worker` package's `uvicorn_worker.UvicornWorker`,
which is what `worker_class` below points at.

Usage:
    uv run --package forecast-api gunicorn -c gunicorn_conf.py ecolens_forecast_api.main:app

Reads bind host/port and worker count from this service's own
`Settings` (`FORECAST_*` env vars) rather than duplicating that as
separate Gunicorn-specific env vars -- one source of truth for "where
does this service listen," same rationale as everything else in
`settings.py`.
"""

from __future__ import annotations

import multiprocessing
import os
import shutil
from pathlib import Path

# Must happen before `ecolens_forecast_api` (and therefore `metrics.py`,
# which creates the actual Counter/Histogram objects at import time) is
# ever imported by a worker -- prometheus_client decides per-metric
# whether to use its multiprocess-aware storage backend based on
# whether this env var is already set when the metric object is
# created, not just at scrape time. Setting it here, in the master's
# config-load step, means every forked worker inherits it before it
# imports the app. Cleared and recreated on each gunicorn start so a
# previous crashed run's stale per-PID files can't leak into new counts.
_multiproc_dir = Path(
    os.environ.setdefault(
        "PROMETHEUS_MULTIPROC_DIR",
        "/tmp/ecolens_forecast_api_prometheus",  # nosec B108 - not a secret path, just a scratch dir; overridable via the env var
    )
)
shutil.rmtree(_multiproc_dir, ignore_errors=True)
_multiproc_dir.mkdir(parents=True, exist_ok=True)

from ecolens_forecast_api.settings import get_forecast_api_settings  # noqa: E402

_settings = get_forecast_api_settings()


def _default_worker_count() -> int:
    """(2 * CPU cores) + 1, the standard Gunicorn sizing formula, capped at 8.

    Uncapped, this comfortably overshoots useful concurrency on a
    32-core CI/build host for a service that's I/O-bound on Postgres,
    not CPU-bound -- each worker holds its own `pg_min_pool`..
    `pg_max_pool` connections, so worker count multiplies total DB
    connections. 8 is a sane production ceiling to raise deliberately
    (via `web_concurrency`), not stumble into via `os.cpu_count()`.
    """
    return min((2 * multiprocessing.cpu_count()) + 1, 8)


bind = f"{_settings.api_host}:{_settings.api_port}"
workers = _settings.web_concurrency or _default_worker_count()
worker_class = "uvicorn_worker.UvicornWorker"

# Liveness probes (docker-compose/k8s) should hit /health, not wait on a
# slow worker boot; keep these generous but bounded rather than infinite.
timeout = 30
graceful_timeout = 30
keepalive = 5

# Container-friendly: log to stdout/stderr, let the orchestrator collect it,
# don't write to a log file that outlives the container.
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Recycle workers periodically to bound the impact of any slow memory
# creep (e.g. an unbounded cache-adjacent leak) without needing a human
# to notice and restart the service. jitter avoids a thundering-herd
# restart when many workers were started at the same moment.
max_requests = 10_000
max_requests_jitter = 1_000


def child_exit(server, worker):  # noqa: ARG001, ANN001 - gunicorn hook signature, not ours to change
    """Gunicorn hook, auto-detected by name: fires in the master when a
    worker exits (recycled via max_requests, killed, crashed, ...).
    Marks that worker's PID dead in PROMETHEUS_MULTIPROC_DIR so /metrics
    stops aggregating its now-stale shard instead of double-counting a
    worker that no longer exists.
    """
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)
