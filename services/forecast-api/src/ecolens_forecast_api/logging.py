"""Thin stdlib structured-logging wrapper.

Same event-style convention as data-pipeline's
`ecolens.shared.observability.logging` (`log.info("pool.connect",
host=...)`), reimplemented here rather than imported so forecast-api
stays a standalone deployable with no import-time dependency on the
data-pipeline package.
"""

from __future__ import annotations

import logging
from typing import Any


class EventLogger:
    """Wraps a stdlib `Logger`; keyword args are appended as `key=value`."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _emit(self, level: int, event: str, **fields: Any) -> None:
        if fields:
            suffix = " ".join(f"{k}={v!r}" for k, v in fields.items())
            self._logger.log(level, "%s %s", event, suffix)
        else:
            self._logger.log(level, event)

    def debug(self, event: str, **fields: Any) -> None:
        self._emit(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self._emit(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit(logging.ERROR, event, **fields)


def get_logger(name: str) -> EventLogger:
    return EventLogger(logging.getLogger(name))


__all__ = ["EventLogger", "get_logger"]
