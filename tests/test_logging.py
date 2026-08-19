"""Structured logging tests."""

import json
import logging
import sys

from core.logging import ApplicationFormatter


def test_json_formatter_includes_redacted_exception_stack_trace() -> None:
    """logger.exception 的根因必须可见，但敏感键值不可出现在日志中。"""
    formatter = ApplicationFormatter(json_output=True, include_stacktrace=True)
    try:
        raise RuntimeError("token=private-value")
    except RuntimeError:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="operation_failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    payload = json.loads(formatter.format(record))

    assert payload["error"]["type"] == "RuntimeError"
    assert payload["error"]["message"] == "token=***"
    assert "RuntimeError" in payload["error"]["stack_trace"]
    assert "private-value" not in payload["error"]["stack_trace"]
    assert "token=***" in payload["error"]["stack_trace"]
