"""JSON-formatted logging for production-style observability.

Instead of plain text, every log line is a single-line JSON object.
This makes logs trivially parseable by ingest pipelines (Loki, ELK,
Datadog) and lets us attach structured fields (request_id, durations,
counts) without inventing a parsing convention.

Each record carries:

    {
        "timestamp": "2026-05-07T18:37:42+00:00",
        "level": "INFO",
        "logger": "app.services.ingest",
        "message": "indexed repo=... duration=2.34s",
        "request_id": "uuid or '-'",
        "exc_info": "<traceback>"  // only on exceptions
    }

The `request_id` field is read from `app.middleware.request_id_var`,
a ContextVar populated by the request_id middleware. Outside any
request (startup, shutdown, background tasks after the request has
returned) the default `-` is emitted, which makes those records easy
to spot when grepping production logs.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.middleware.request_id import request_id_var


class JsonFormatter(logging.Formatter):
    """Render LogRecord instances as single-line JSON.

    `default=str` is the safety net for non-serializable objects that
    sneak into `record.args` or `record.__dict__` — datetimes, paths,
    UUIDs. We'd rather emit them as `str()` than crash the log handler.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            # `getMessage()` performs the lazy %-substitution. If we
            # used `record.msg` directly, lines like `logger.info("x=%s", v)`
            # would emit the raw template string instead of the
            # substituted value — a classic logging bug.
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger.

    Idempotent: clears existing handlers before adding our own, so
    calling this multiple times (e.g. in tests that re-create the app)
    doesn't double-emit every log line.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
