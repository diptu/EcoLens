"""Event-driven replacement for the warehouse's old incremental cron.

`ecolens.shared.events.rabbitmq.publish_data_ingested` fires once per
successful `duckdb_store.write_historical()` call. `WarehouseEventConsumer`
listens on that same queue and triggers an incremental `WarehouseRunner`
run in response -- so the warehouse refreshes as soon as new data lands
instead of polling on a fixed schedule.

Debounced, not one-run-per-event: a single ingestion cycle
(`cron_ingest_all.sh`) writes up to 5 sources in quick succession, each
firing its own event. Without debouncing that's 5 overlapping
incremental runs for one cycle's worth of data, all but the last of
them wasted work. Every event received resets a `debounce_seconds`
timer; the actual `WarehouseRunner` run only fires once events stop
arriving for that long, so a burst collapses into exactly one run.

Overlap-guarded, not overlap-blocked: if new events arrive *while* a
run is already in progress, they don't get lost (a naive "ignore while
running" would silently drop data that arrived mid-run) -- they set a
"rerun requested" flag that fires one more run immediately after the
current one finishes, rather than making the newly-arrived data wait
for a full new debounce window.

Messages are acked (via `message.process()`) regardless of whether the
triggered run succeeds -- a failed `WarehouseRunner` run is already
recorded in `data/log/warehouse-runs.jsonl` (the same place a
cron-triggered failure would land); redelivering the message wouldn't
add information, just risk a redelivery loop against a broker that
mostly exists to say "something changed," not to guarantee this
specific run.

Persists a small heartbeat (`data/log/warehouse_consumer_status.json`)
on every state transition -- listening started, event received, run
triggered/completed -- purely so `GET /warehouse/consumer-status`
(`ecolens.warehouse.api.runner_router`) has something to report to the
dashboard's admin section. The consumer itself has no HTTP surface of
its own; this file is the entire interface between the two.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aio_pika

from ecolens.shared.observability.logging import get_logger

from .orchestrator import WarehouseRunner
from ecolens.warehouse.core.runner_settings import (
    WarehouseRunnerSettings,
    get_warehouse_runner_settings,
)

log = get_logger(__name__)

# Long enough to cover cron_ingest_all.sh's ~1min, 5-source sequential
# run (see its own timing notes) with margin, short enough that a
# single off-cycle write (e.g. a manual /ingestion/historical backfill)
# still triggers a warehouse run within a reasonable time.
DEFAULT_DEBOUNCE_SECONDS = 45.0

STATUS_FILENAME = "warehouse_consumer_status.json"


class WarehouseEventConsumer:
    """Consumes "data ingested" events and triggers debounced,
    overlap-guarded incremental `WarehouseRunner` runs.
    """

    def __init__(
        self,
        settings: WarehouseRunnerSettings | None = None,
        *,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        runner: WarehouseRunner | None = None,
    ) -> None:
        self.settings = settings or get_warehouse_runner_settings()
        self.debounce_seconds = debounce_seconds
        self._runner = runner or WarehouseRunner(self.settings)
        self._debounce_task: asyncio.Task[None] | None = None
        self._run_in_progress = False
        self._rerun_requested = False
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._listening_since: str | None = None
        self._last_event: dict[str, Any] | None = None
        self._last_run: dict[str, Any] | None = None

    @property
    def _status_path(self) -> Path:
        return self.settings.log_dir / STATUS_FILENAME

    def _write_status(self) -> None:
        status = {
            "listening_since": self._listening_since,
            "last_event": self._last_event,
            "last_run": self._last_run,
            "run_in_progress": self._run_in_progress,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._status_path.parent.mkdir(parents=True, exist_ok=True)
            self._status_path.write_text(json.dumps(status))
        except OSError as exc:  # noqa: BLE001 - a status heartbeat must never crash the daemon
            log.warning("event_consumer.status_write_failed", error=str(exc))

    async def run_forever(self, rabbitmq_url: str, queue_name: str) -> None:
        """Connect and consume until cancelled. Reconnects automatically
        on connection loss (`aio_pika.connect_robust`) -- appropriate for
        a long-running host daemon that should outlive a broker restart.
        """
        self._connection = await aio_pika.connect_robust(rabbitmq_url)
        async with self._connection:
            channel = await self._connection.channel()
            await channel.set_qos(prefetch_count=10)
            queue = await channel.declare_queue(queue_name, durable=True)
            log.info("event_consumer.listening", queue=queue_name)
            self._listening_since = datetime.now(timezone.utc).isoformat()
            self._write_status()
            async with queue.iterator() as messages:
                async for message in messages:
                    async with message.process():
                        await self._on_event(message)

    async def _on_event(self, message: aio_pika.abc.AbstractIncomingMessage) -> None:
        try:
            payload: dict[str, Any] = json.loads(message.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("event_consumer.bad_payload", error=str(exc))
            return
        log.info(
            "event_consumer.event_received",
            source=payload.get("source"),
            rows=payload.get("rows"),
            run_id=payload.get("run_id"),
        )
        self._last_event = {
            "source": payload.get("source"),
            "rows": payload.get("rows"),
            "run_id": payload.get("run_id"),
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_status()
        self._schedule_debounced_run()

    def _schedule_debounced_run(self) -> None:
        if self._debounce_task is not None and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._debounce_and_run())

    async def _debounce_and_run(self) -> None:
        try:
            await asyncio.sleep(self.debounce_seconds)
        except asyncio.CancelledError:
            # Superseded by a newer event's debounce window -- not an
            # error, just let this one go quietly.
            return
        await self._trigger_run()

    async def _trigger_run(self) -> None:
        if self._run_in_progress:
            self._rerun_requested = True
            return
        self._run_in_progress = True
        triggered_at = datetime.now(timezone.utc).isoformat()
        self._write_status()
        try:
            log.info("event_consumer.run_triggered")
            result = await self._runner.run(mode="incremental")
            log.info(
                "event_consumer.run_complete",
                success=result.success,
                duration_s=result.duration_seconds,
            )
            self._last_run = {
                "triggered_at": triggered_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "success": result.success,
                "duration_seconds": result.duration_seconds,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 - daemon must survive one bad run
            log.error("event_consumer.run_failed", error=str(exc))
            self._last_run = {
                "triggered_at": triggered_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "success": False,
                "duration_seconds": None,
                "error": str(exc),
            }
        finally:
            self._run_in_progress = False
            self._write_status()

        if self._rerun_requested:
            self._rerun_requested = False
            await self._trigger_run()

    async def stop(self) -> None:
        if self._debounce_task is not None:
            self._debounce_task.cancel()
        if self._connection is not None:
            await self._connection.close()


__all__ = ["WarehouseEventConsumer", "DEFAULT_DEBOUNCE_SECONDS"]
