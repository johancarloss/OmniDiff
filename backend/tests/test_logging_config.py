"""Unit tests for the JSON logging formatter.

These exercise the formatter against synthetic LogRecord instances
without touching the global logging tree — fast, deterministic, no
side effects on other tests.
"""

from __future__ import annotations

import json
import logging

from app.middleware.request_id import request_id_var
from app.services.logging_config import JsonFormatter, setup_logging


def _make_record(
    *,
    msg: str = "hello %s",
    args: tuple[object, ...] = ("world",),
    level: int = logging.INFO,
    name: str = "app.test",
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_formatter_emits_valid_json() -> None:
    formatter = JsonFormatter()
    record = _make_record()

    line = formatter.format(record)

    parsed = json.loads(line)
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "app.test"
    assert parsed["message"] == "hello world"  # lazy %-formatting was applied
    assert "timestamp" in parsed


def test_formatter_includes_request_id_from_contextvar() -> None:
    formatter = JsonFormatter()
    token = request_id_var.set("trace-xyz-001")
    try:
        record = _make_record()
        line = formatter.format(record)
    finally:
        request_id_var.reset(token)

    parsed = json.loads(line)
    assert parsed["request_id"] == "trace-xyz-001"


def test_formatter_emits_dash_request_id_when_unset() -> None:
    """Outside a request context, `request_id_var` reads its default
    `-`. The formatter must emit that as-is so log consumers can tell
    apart request-scoped logs from background ones."""
    formatter = JsonFormatter()
    record = _make_record()
    line = formatter.format(record)
    parsed = json.loads(line)
    assert parsed["request_id"] == "-"


def test_formatter_serializes_exception() -> None:
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="app.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="something failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    line = formatter.format(record)

    parsed = json.loads(line)
    assert parsed["level"] == "ERROR"
    assert "ValueError" in parsed["exc_info"]
    assert "boom" in parsed["exc_info"]


def test_formatter_handles_non_serializable_args() -> None:
    """A datetime or Path inside the formatted message must not crash
    the formatter — `default=str` falls back to repr-ish output."""
    formatter = JsonFormatter()
    from datetime import datetime

    record = _make_record(msg="ran at %s", args=(datetime(2026, 5, 7, 12, 0, 0),))
    line = formatter.format(record)
    parsed = json.loads(line)
    assert "2026-05-07" in parsed["message"]


def test_setup_logging_replaces_handlers() -> None:
    """Calling setup_logging twice must not duplicate handlers, or
    every log line would be emitted N times after N reloads (e.g.
    in test fixtures that recreate the app)."""
    setup_logging()
    first_handlers = list(logging.getLogger().handlers)
    setup_logging()
    second_handlers = list(logging.getLogger().handlers)

    assert len(second_handlers) == 1
    # Different handler instance, but the count is what protects against
    # duplication. Identity check would over-constrain the contract.
    assert isinstance(second_handlers[0], logging.StreamHandler)
    assert isinstance(first_handlers[0], logging.StreamHandler)
