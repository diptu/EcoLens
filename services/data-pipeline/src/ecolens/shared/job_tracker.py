"""Generic in-memory background-job tracker.

Extracted from `ecolens.ingestion.api`'s original `/ingestion/historical`
job-status mechanism after `ecolens.forecasting.api` needed the exact
same "trigger returns a job_id, poll it for running/completed/failed"
shape a second time -- one tracker, reused, instead of two divergent
copies of the same ~40 lines.

Each call site owns its own `JobTracker()` instance (rather than one
shared global) so e.g. a flood of ingestion jobs can't evict forecasting
jobs' history, and each domain's router shapes `JobStatus.result`/`.meta`
into whatever response fields make sense for it (ingestion returns
`upserted`; forecasting returns a `TrainResult` summary) -- this module
only owns the generic running/completed/failed bookkeeping, not any
domain-specific response shape.

Plain in-memory dict, not a durable store: resets on process restart,
not shared across multiple worker processes. Fine for `make pipeline`'s
single-process dev server; a production multi-worker deployment would
need a shared store (Redis, a DB table) instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)


@dataclass
class JobStatus:
    """One tracked job's current state.

    `meta` is whatever the caller wants to remember about the job's
    *inputs* (e.g. source/date-range for an ingestion job) -- set once,
    at `start()`, and never touched again. `result` is the job
    function's return value, set once it completes -- shape is up to
    the caller (an int upserted-count, a small dict, a dataclass, ...).
    """

    job_id: str
    status: Literal["running", "completed", "failed"]
    started_at: str
    finished_at: str | None = None
    result: Any | None = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class JobTracker:
    """Bounded in-memory `job_id -> JobStatus` store + the background-task
    wrapper that keeps it updated.
    """

    def __init__(self, max_jobs: int = 500) -> None:
        self._max_jobs = max_jobs
        self._jobs: dict[str, JobStatus] = {}

    def start(self, **meta: Any) -> str:
        """Registers a new `running` job, returns its `job_id`.

        Call this synchronously in the request handler (before
        scheduling the actual work via `BackgroundTasks.add_task`) so
        the `job_id` can be returned to the caller immediately.
        """
        job_id = uuid4().hex
        if len(self._jobs) >= self._max_jobs:
            # Dicts preserve insertion order since Python 3.7 -- the
            # oldest key is always `next(iter(...))`.
            self._jobs.pop(next(iter(self._jobs)))
        self._jobs[job_id] = JobStatus(
            job_id=job_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            meta=meta,
        )
        return job_id

    def get(self, job_id: str) -> JobStatus | None:
        return self._jobs.get(job_id)

    def clear(self) -> None:
        """Test-only: resets the tracker to empty between test cases."""
        self._jobs.clear()

    async def run(self, job_id: str, fn, *args: Any, **kwargs: Any) -> None:  # noqa: ANN001 - fn's signature varies per call site by design
        """The actual `BackgroundTasks.add_task` target: awaits
        `fn(*args, **kwargs)`, then updates `self._jobs[job_id]` to
        `completed` (with `fn`'s return value as `result`) or `failed`
        (with the exception message as `error`) -- a last-resort catch,
        since `fn` is expected to already handle its own expected
        failure modes internally; this just guarantees the job's status
        always resolves to something, even on a genuine bug in `fn`.
        """
        job = self._jobs[job_id]
        try:
            job.result = await fn(*args, **kwargs)
            job.status = "completed"
        except Exception as exc:  # noqa: BLE001 - last-resort so job status always resolves
            job.status = "failed"
            job.error = str(exc)
            log.error("job_tracker.job_failed", job_id=job_id, error=str(exc))
        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()


__all__ = ["JobStatus", "JobTracker"]
