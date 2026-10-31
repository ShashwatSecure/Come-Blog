import json
import logging
import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_RESERVED = set(logging.LogRecord(None, 0, "", 0, "", (), None).__dict__)


class JsonFormatter(logging.Formatter):
    """Emit one machine-readable log event per line."""

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                event[key] = value
        if record.exc_info:
            event["exception"] = self.formatException(record.exc_info)
        return json.dumps(event, default=str)


def configure_logging() -> None:
    level = os.getenv("COMEBLOG_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    logging.captureWarnings(True)


logger = logging.getLogger("come_blog")

_context: ContextVar[dict[str, Any] | None] = ContextVar("come_blog_log_context", default=None)


def log_event(level: int, event: str, message: str | None = None, *, exc_info: bool = False, **fields: Any) -> None:
    """Emit one structured event with the current request/run context attached."""
    logger.log(level, message or event, extra={**(_context.get() or {}), **fields, "event": event}, exc_info=exc_info)


@contextmanager
def logging_context(**fields: Any) -> Generator[None, None, None]:
    """Temporarily bind correlation fields to logs in the current execution context."""
    current = _context.get() or {}
    token = _context.set({**current,**{key: value for key, value in fields.items() if value is not None}})
    try:
        yield
    finally:
        _context.reset(token)
