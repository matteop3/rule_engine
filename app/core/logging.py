"""Structured logging configuration with request correlation."""

import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

# Context variable for request correlation
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIDFilter(logging.Filter):
    """Injects request_id from contextvars into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()  # type: ignore[attr-defined]
        return True


def setup_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure root logger and uvicorn loggers. Call once at app startup."""
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIDFilter())

    if json_output:
        handler.setFormatter(
            JsonFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s (%(request_id)s) %(message)s"))

    root.addHandler(handler)

    # Route uvicorn loggers through the same handler so all output
    # shares a single format (JSON or plain). Without this, uvicorn
    # access logs would remain in plain text alongside JSON app logs.
    for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(uvicorn_logger_name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True


def get_uvicorn_log_config(json_output: bool = True) -> dict:
    """
    Returns a log config dict for uvicorn that routes access/error logs
    through the same JSON formatter as the application.

    Use this when launching uvicorn programmatically via uvicorn.run(log_config=...).
    When uvicorn is launched via CLI (Dockerfile / docker-compose), the loggers
    are configured in setup_logging() instead.
    """
    if not json_output:
        # Empty dict makes uvicorn fall back to its default plain-text loggers.
        return {}

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.json.JsonFormatter",
                "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            }
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "stream": "ext://sys.stdout",
                "filters": [],
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {
                "handlers": ["default"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["default"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }
