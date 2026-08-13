"""Structured logging for the ingestion service.

JSON-rendered structlog. `request_id` (API requests) and `run_id` (ingest
runs) are bound via structlog's contextvars support, so every log line
emitted within that request/run carries both automatically. Ported
verbatim from `data-pipeline`'s identical module (`services/ingestion/
TODO.md` Phase 1) -- fully generic, no ingestion-specific logic.

`_add_trace_context`/`_static_fields` (`TODO.md` Observability Phase 1's
"Structured Logging Integration") close a real, previously-open gap:
"no service's structlog config binds trace_id/span_id (or even service/
environment/version) as static context yet". `_add_trace_context` reads
whatever span is current at each individual log call -- unlike
`request_id`/`run_id` above, this can't be a one-time contextvars bind,
since a log line inside `pipeline.tasks._common.standard_run`'s
`ingestion.standard_run` span needs a *different* trace_id/span_id than
one emitted before that span opened or after it closed. A real no-op
(no fields added) when tracing is disabled or there's no current span --
`core/tracing.py`'s `get_tracer()` always returns a valid no-op-safe
tracer, and `trace.get_current_span()` returns OTel's own INVALID span
in that case, same "safe to call unconditionally" contract.
"""

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
    """Configure structlog for JSON output. Safe to call more than once."""
    global _configured
    if _configured:
        return

    # Local imports -- `app.core.config`/`app.__version__` don't import
    # this module, so there's no real cycle, but importing at call time
    # (not module import time) keeps this module importable standalone
    # (e.g. from a script that only wants `get_logger` before `Settings`
    # is otherwise needed) the same way it always was before this change.
    from app import __version__
    from app.core.config import get_settings

    settings = get_settings()
    level_no = getattr(logging, level.upper())
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level_no)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _static_fields("ingestion", settings.environment, __version__),
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


# Alias kept for symmetry with `bind_request_id`; matches data-pipeline's
# `pipeline.tasks._common` import name for the same function.
bind_run_id = set_run_id


def clear_context() -> None:
    """Reset bound context vars (call at the start of a request/run)."""
    structlog.contextvars.clear_contextvars()
