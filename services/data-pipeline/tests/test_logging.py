import json

import structlog

from app.core import logging as ecolens_logging


def _reset_module_state():
    ecolens_logging._configured = False


def test_configure_logging_is_idempotent():
    _reset_module_state()
    ecolens_logging.configure_logging("INFO")
    assert ecolens_logging._configured is True
    # Second call must not raise and must stay a no-op.
    ecolens_logging.configure_logging("INFO")
    assert ecolens_logging._configured is True


def test_get_logger_emits_json(capsys):
    _reset_module_state()
    ecolens_logging.clear_context()
    log = ecolens_logging.get_logger("test")
    log.info("hello", foo="bar")

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["event"] == "hello"
    assert payload["foo"] == "bar"
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_request_id_and_run_id_are_bound_to_log_context():
    ecolens_logging.clear_context()
    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as captured:
        ecolens_logging.bind_request_id("req-123")
        ecolens_logging.bind_run_id("run-456")
        structlog.get_logger("test").info("bound-event")
    ecolens_logging.clear_context()

    assert len(captured) == 1
    assert captured[0]["request_id"] == "req-123"
    assert captured[0]["run_id"] == "run-456"


def test_clear_context_removes_bound_ids():
    ecolens_logging.bind_request_id("req-999")
    ecolens_logging.clear_context()
    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as captured:
        structlog.get_logger("test").info("after-clear")

    assert "request_id" not in captured[0]
