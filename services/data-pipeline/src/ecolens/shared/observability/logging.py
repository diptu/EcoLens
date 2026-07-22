"""Structured logging for ecoLens services.

File path:
    services/data-pipeline/src/ecolens/shared/observability/logging.py

Thin wrapper around stdlib `logging` so call sites can log event-style:
`log.info("mongo.client_created", uri_host=..., db_name=...)` instead of
hand-formatting message strings. No external dependency (no structlog).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from ecolens.config import get_settings

_configured = False


class _StructuredLogger:
    """Adapts a stdlib `logging.Logger` to accept `event, **fields` calls."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, level: int, event: str, **fields: Any) -> None:
        if fields:
            rendered = " ".join(f"{key}={value!r}" for key, value in fields.items())
            message = f"{event} {rendered}"
        else:
            message = event
        self._logger.log(level, message)

    def debug(self, event: str, **fields: Any) -> None:
        self._log(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self._log(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._log(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._log(logging.ERROR, event, **fields)


def _configure_root() -> None:
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    _configured = True


def get_logger(name: str) -> _StructuredLogger:
    """Return a structured logger for `name` (usually `__name__`)."""
    _configure_root()
    return _StructuredLogger(logging.getLogger(name))


__all__ = ["get_logger"]
