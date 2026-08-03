"""Structured logging for the data-pipeline service.

JSON-rendered structlog. `request_id` (API requests, ECO-D12) and `run_id`
(ingest/ML pipeline runs) are bound via structlog's contextvars support, so
every log line emitted within that request/run carries both automatically.
"""

from __future__ import annotations

import logging
import sys

import structlog

_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for JSON output. Safe to call more than once."""
    global _configured
    if _configured:
        return

    level_no = getattr(logging, level.upper())
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level_no)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_no),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(
    *args: object, **kwargs: object
) -> structlog.typing.FilteringBoundLogger:
    """Return a structlog logger, configuring logging on first use if needed."""
    if not _configured:
        configure_logging()
    return structlog.get_logger(*args, **kwargs)


def bind_request_id(request_id: str) -> None:
    """Attach `request_id` to every log line emitted in the current context."""
    structlog.contextvars.bind_contextvars(request_id=request_id)


def set_run_id(run_id: str) -> None:
    """Attach `run_id` to every log line emitted in the current context."""
    structlog.contextvars.bind_contextvars(run_id=run_id)


# Alias kept for symmetry with `bind_request_id`; `set_run_id` is the name
# app.service.pipeline.tasks._common actually imports.
bind_run_id = set_run_id


def clear_context() -> None:
    """Reset bound context vars (call at the start of a request/run)."""
    structlog.contextvars.clear_contextvars()
