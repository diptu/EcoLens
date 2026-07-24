"""Tests for ecolens.shared.job_tracker (extracted from ingestion.api's
original job-status mechanism; reused by forecasting.api's incremental
training endpoint too).
"""

from __future__ import annotations

import pytest

from ecolens.shared.job_tracker import JobTracker


class TestJobTrackerStart:
    def test_start_registers_a_running_job_with_meta(self):
        tracker = JobTracker()
        job_id = tracker.start(source="bom", start_date="2026-01-01")

        job = tracker.get(job_id)
        assert job is not None
        assert job.status == "running"
        assert job.meta == {"source": "bom", "start_date": "2026-01-01"}
        assert job.result is None
        assert job.error is None
        assert job.finished_at is None

    def test_get_unknown_job_id_returns_none(self):
        tracker = JobTracker()
        assert tracker.get("no-such-job") is None

    def test_start_evicts_oldest_job_once_max_jobs_reached(self):
        tracker = JobTracker(max_jobs=2)
        first = tracker.start(n=1)
        tracker.start(n=2)
        tracker.start(n=3)  # should evict `first`

        assert tracker.get(first) is None
        assert len(tracker._jobs) == 2  # noqa: SLF001 - test-only internals peek


class TestJobTrackerRun:
    @pytest.mark.asyncio
    async def test_completed_job_stores_the_return_value(self):
        tracker = JobTracker()
        job_id = tracker.start()

        async def fn(x, y):
            return x + y

        await tracker.run(job_id, fn, 2, 3)

        job = tracker.get(job_id)
        assert job.status == "completed"
        assert job.result == 5
        assert job.error is None
        assert job.finished_at is not None

    @pytest.mark.asyncio
    async def test_failed_job_stores_the_error_message(self):
        tracker = JobTracker()
        job_id = tracker.start()

        async def fn():
            raise RuntimeError("boom")

        await tracker.run(job_id, fn)

        job = tracker.get(job_id)
        assert job.status == "failed"
        assert job.error == "boom"
        assert job.result is None
        assert job.finished_at is not None


class TestJobTrackerClear:
    def test_clear_empties_the_tracker(self):
        tracker = JobTracker()
        job_id = tracker.start()
        tracker.clear()
        assert tracker.get(job_id) is None
