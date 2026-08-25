"""Structured logging tests."""

import json
import logging
import sys

from core.logging_config import ApplicationFormatter


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


def test_json_formatter_redacts_nested_http_style_credential_fields() -> None:
    """MCP 参数和结果允许记录，但常见凭据字段必须保留脱敏。"""
    formatter = ApplicationFormatter(json_output=True, include_stacktrace=False)
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="mcp_tool_completed",
        args=(),
        exc_info=None,
    )
    record.fields = {
        "arguments": {
            "body": {"name": "payments", "api-key": "private-key"},
            "headers": {"Authorization": "Bearer private-token", "X-Trace-ID": "request-123"},
        },
        "result": {"Authorization": "Bearer private-token", "status": "ok"},
    }

    payload = json.loads(formatter.format(record))

    assert payload["arguments"]["body"]["name"] == "payments"
    assert payload["arguments"]["body"]["api-key"] == "***"
    assert payload["arguments"]["headers"] == {"Authorization": "***", "X-Trace-ID": "request-123"}
    assert payload["result"]["Authorization"] == "***"
    assert payload["result"]["status"] == "ok"
