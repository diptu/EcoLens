"""Structured logging for forecast-api. JSON-rendered structlog, same
setup as `data-pipeline`'s `app.core.logging` (intentionally
duplicated — trivial, no cross-service state to share)."""

from __future__ import annotations

import logging
import sys

import structlog

_configured = False


def configure_logging(level: str = "INFO") -> None:
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
    if not _configured:
        configure_logging()
    return structlog.get_logger(*args, **kwargs)
