"""Structured logging for forecast-api. JSON-rendered structlog, same
setup as `data-pipeline`'s `app.core.logging` (intentionally
duplicated — trivial, no cross-service state to share).

`_add_trace_context`/`_static_fields` (`TODO.md` Observability Phase 1's
"Structured Logging Integration") -- see `services/ingestion`'s
identical module for the full reasoning (why this can't be a one-time
contextvars bind, and why it's a real no-op when tracing is disabled)."""

from __future__ import annotations

import logging
import sys

import structlog
from opentelemetry import trace

_configured = False


def _add_trace_context(
    logger: structlog.typing.WrappedLogger,
    method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


def _static_fields(
    service: str, environment: str, version: str
) -> structlog.typing.Processor:
    def processor(
        logger: structlog.typing.WrappedLogger,
        method_name: str,
        event_dict: structlog.typing.EventDict,
    ) -> structlog.typing.EventDict:
        event_dict.setdefault("service", service)
        event_dict.setdefault("environment", environment)
        event_dict.setdefault("version", version)
        return event_dict

    return processor


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return

    from app import __version__
    from app.core.config import get_settings

    settings = get_settings()
    level_no = getattr(logging, level.upper())
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level_no)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _static_fields("forecast-api", settings.environment, __version__),
            _add_trace_context,
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
