"""Tests for ecolens.shared.events.rabbitmq.publish_data_ingested.

Mocks `_publish` (the actual pika I/O) so these never touch a real
broker -- the point of these tests is the best-effort contract
(never raises, logs on failure), not pika's own wire behavior.
"""

from __future__ import annotations

import pytest

import ecolens.shared.events.rabbitmq as rabbitmq_module
from ecolens.shared.events.rabbitmq import publish_data_ingested


class TestPublishDataIngested:
    def test_happy_path_calls_publish_with_expected_payload(self, monkeypatch):
        calls = []

        def fake_publish(url, queue, payload):
            calls.append((url, queue, payload))

        monkeypatch.setattr(rabbitmq_module, "_publish", fake_publish)
        publish_data_ingested("bom", run_id="run-1", rows=42)

        assert len(calls) == 1
        url, queue, payload = calls[0]
        assert queue == "ecolens.warehouse.trigger"
        assert payload["source"] == "bom"
        assert payload["run_id"] == "run-1"
        assert payload["rows"] == 42
        assert "ts" in payload

    def test_broker_unreachable_does_not_raise(self, monkeypatch):
        def raises(url, queue, payload):
            raise ConnectionError("no route to host")

        monkeypatch.setattr(rabbitmq_module, "_publish", raises)
        # Must not raise -- ingestion's write path depends on this.
        publish_data_ingested("bom", run_id="run-1", rows=1)

    @pytest.mark.parametrize(
        "exc", [ConnectionError("down"), TimeoutError("slow"), RuntimeError("boom")]
    )
    def test_any_publish_failure_is_swallowed(self, monkeypatch, exc):
        monkeypatch.setattr(
            rabbitmq_module,
            "_publish",
            lambda *a, **kw: (_ for _ in ()).throw(exc),
        )
        publish_data_ingested("aemo_nem", run_id="run-2", rows=5)
