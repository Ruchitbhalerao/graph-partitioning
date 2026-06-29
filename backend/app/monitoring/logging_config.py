"""Structured logging configuration for the optimization system.

Provides JSON-formatted logging with performance context and
integration with the metrics system.
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from collections import deque


class JSONFormatter(logging.Formatter):
    """Format log records as JSON lines for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Include extra fields from logging extra=
        for key, value in getattr(record, "extra", {}).items():
            log_entry[key] = value

        return json.dumps(log_entry, default=str)


class PerformanceContextLogger:
    """Logger wrapper that adds performance context to log messages.

    Usage:
        logger = PerformanceContextLogger(__name__)
        logger.info("Operation complete", duration=1.5, dealers=500)
    """

    def __init__(self, name: str, level: int = logging.INFO):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        self._context: Dict[str, Any] = {}

        # Add JSON handler if none exists
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(JSONFormatter())
            self._logger.addHandler(handler)

    def bind(self, **kwargs):
        """Bind context to all subsequent log messages (thread-safe-ish)."""
        self._context.update(kwargs)
        return self

    def _log(self, level: int, msg: str, **kwargs):
        extra = {**self._context, **kwargs}
        self._logger.log(level, msg, extra=extra)

    def info(self, msg: str, **kwargs):
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs):
        self._log(logging.ERROR, msg, **kwargs)

    def debug(self, msg: str, **kwargs):
        self._log(logging.DEBUG, msg, **kwargs)

    def timed(self, msg: str, **kwargs):
        """Context manager that logs start/end with duration."""
        return _TimedLogContext(self, msg, **kwargs)


class _TimedLogContext:
    def __init__(self, logger: PerformanceContextLogger, msg: str, **kwargs):
        self.logger = logger
        self.msg = msg
        self.kwargs = kwargs
        self._start: Optional[float] = None

    def __enter__(self):
        self._start = time.perf_counter()
        self.logger.info(f"START: {self.msg}", **self.kwargs)
        return self

    def __exit__(self, *args):
        elapsed = time.perf_counter() - self._start
        self.logger.info(
            f"END: {self.msg}",
            duration_sec=round(elapsed, 4),
            **self.kwargs,
        )


class LogBuffer:
    """In-memory circular buffer of recent log entries for live streaming."""

    def __init__(self, max_entries: int = 500):
        self._buffer: deque = deque(maxlen=max_entries)
        self._handler = _BufferHandler(self._buffer)

    @property
    def handler(self) -> logging.Handler:
        return self._handler

    def recent(self, n: int = 50) -> list:
        return list(self._buffer)[-n:]

    def clear(self):
        self._buffer.clear()


class _BufferHandler(logging.Handler):
    def __init__(self, buffer: deque):
        super().__init__()
        self._buffer = buffer
        self.setFormatter(JSONFormatter())

    def emit(self, record: logging.LogRecord):
        try:
            self._buffer.append(self.format(record))
        except Exception:
            pass


# Configure root logger
def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    log_buffer: Optional[LogBuffer] = None,
):
    """Configure the root logger with structured JSON output."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove default handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # Add stdout JSON handler
    if json_format:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        root.addHandler(handler)

    # Add buffer handler if provided
    if log_buffer:
        root.addHandler(log_buffer.handler)

    # Set third-party log levels
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("networkx").setLevel(logging.WARNING)
    logging.getLogger("fiona").setLevel(logging.WARNING)
    logging.getLogger("shapely").setLevel(logging.WARNING)
