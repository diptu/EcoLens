"""Tests for ecolens.warehouse.service.event_consumer.WarehouseEventConsumer.

Never touches a real broker -- `_on_event`/`_trigger_run` are exercised
directly with a fake `WarehouseRunner`, so these test the
debounce/overlap-guard logic in isolation from aio_pika's connection
handling. `debounce_seconds` is set tiny (real asyncio.sleep, just a
short one) so tests run fast without needing to mock the event loop's
clock. `settings.log_dir` is tmp_path-scoped so the status-heartbeat
file these write never touches the real `data/log/` -- important since
a real consumer daemon may genuinely be running against that same path
at the same time.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ecolens.warehouse.core.runner_settings import WarehouseRunnerSettings
from ecolens.warehouse.models.run_result import RunResult
from ecolens.warehouse.service.event_consumer import WarehouseEventConsumer

DEBOUNCE = 0.03


def _fake_event(source: str = "bom", rows: int = 5) -> bytes:
    return json.dumps(
        {
            "source": source,
            "run_id": "run-1",
            "rows": rows,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    ).encode("utf-8")


def _run_result(success: bool = True) -> RunResult:
    now = datetime.now(timezone.utc)
    return RunResult(started_at=now, finished_at=now, success=success, stages=[])


@pytest.fixture
def fake_runner():
    runner = AsyncMock()
    runner.run.return_value = _run_result()
    return runner


@pytest.fixture
def consumer(fake_runner, tmp_path: Path):
    settings = WarehouseRunnerSettings(log_dir=tmp_path)
    return WarehouseEventConsumer(
        settings=settings, debounce_seconds=DEBOUNCE, runner=fake_runner
    )


class _FakeMessage:
    def __init__(self, body: bytes) -> None:
        self.body = body


class TestDebounce:
    @pytest.mark.asyncio
    async def test_single_event_triggers_one_incremental_run(
        self, consumer, fake_runner
    ):
        await consumer._on_event(_FakeMessage(_fake_event()))
        await asyncio.sleep(DEBOUNCE * 3)

        fake_runner.run.assert_called_once_with(mode="incremental")

    @pytest.mark.asyncio
    async def test_burst_of_events_collapses_to_one_run(self, consumer, fake_runner):
        # 5 events in quick succession (one ingestion cycle's worth of
        # sources), each well within the debounce window of the last.
        for _ in range(5):
            await consumer._on_event(_FakeMessage(_fake_event()))
            await asyncio.sleep(DEBOUNCE / 3)
        await asyncio.sleep(DEBOUNCE * 3)

        fake_runner.run.assert_called_once_with(mode="incremental")

    @pytest.mark.asyncio
    async def test_events_spaced_past_debounce_trigger_separate_runs(
        self, consumer, fake_runner
    ):
        await consumer._on_event(_FakeMessage(_fake_event()))
        await asyncio.sleep(DEBOUNCE * 3)
        await consumer._on_event(_FakeMessage(_fake_event()))
        await asyncio.sleep(DEBOUNCE * 3)

        assert fake_runner.run.call_count == 2

    @pytest.mark.asyncio
    async def test_bad_payload_does_not_raise(self, consumer, fake_runner):
        await consumer._on_event(_FakeMessage(b"not json"))
        # Must not raise -- the consumer daemon must survive a malformed
        # message rather than crashing the whole process.


class TestOverlapGuard:
    @pytest.mark.asyncio
    async def test_event_during_run_triggers_one_rerun_after_it_finishes(
        self, consumer, fake_runner
    ):
        run_started = asyncio.Event()
        release_run = asyncio.Event()

        async def slow_run(mode):
            run_started.set()
            await release_run.wait()
            return _run_result()

        fake_runner.run.side_effect = slow_run

        run_task = asyncio.create_task(consumer._trigger_run())
        await run_started.wait()

        # A new event arrives while the first run is still in flight.
        await consumer._on_event(_FakeMessage(_fake_event()))
        await asyncio.sleep(DEBOUNCE * 3)  # its debounce window elapses mid-run

        assert fake_runner.run.call_count == 1  # still just the in-flight one
        release_run.set()
        await asyncio.sleep(0.05)  # let the in-flight run finish + rerun fire

        assert fake_runner.run.call_count == 2
        await run_task

    @pytest.mark.asyncio
    async def test_run_failure_does_not_raise_and_clears_in_progress_flag(
        self, consumer, fake_runner
    ):
        fake_runner.run.side_effect = RuntimeError("dbt exploded")
        await consumer._trigger_run()  # must not raise
        assert consumer._run_in_progress is False


class TestStatusHeartbeat:
    def _read_status(self, consumer) -> dict:
        return json.loads(consumer._status_path.read_text())

    @pytest.mark.asyncio
    async def test_event_received_updates_status(self, consumer):
        await consumer._on_event(_FakeMessage(_fake_event(source="bom", rows=7)))
        status = self._read_status(consumer)
        assert status["last_event"]["source"] == "bom"
        assert status["last_event"]["rows"] == 7
        assert status["last_event"]["run_id"] == "run-1"
        assert status["run_in_progress"] is False

    @pytest.mark.asyncio
    async def test_successful_run_updates_status(self, consumer, fake_runner):
        fake_runner.run.return_value = _run_result(success=True)
        await consumer._trigger_run()
        status = self._read_status(consumer)
        assert status["last_run"]["success"] is True
        assert status["last_run"]["error"] is None
        assert status["run_in_progress"] is False

    @pytest.mark.asyncio
    async def test_failed_run_updates_status_with_error(self, consumer, fake_runner):
        fake_runner.run.side_effect = RuntimeError("dbt exploded")
        await consumer._trigger_run()
        status = self._read_status(consumer)
        assert status["last_run"]["success"] is False
        assert status["last_run"]["error"] == "dbt exploded"

    @pytest.mark.asyncio
    async def test_run_in_progress_is_true_while_running(self, consumer, fake_runner):
        run_started = asyncio.Event()
        release_run = asyncio.Event()

        async def slow_run(mode):
            run_started.set()
            await release_run.wait()
            return _run_result()

        fake_runner.run.side_effect = slow_run
        run_task = asyncio.create_task(consumer._trigger_run())
        await run_started.wait()

        assert self._read_status(consumer)["run_in_progress"] is True

        release_run.set()
        await run_task
        assert self._read_status(consumer)["run_in_progress"] is False

    def test_status_file_absent_before_any_activity(self, consumer):
        assert not consumer._status_path.exists()
