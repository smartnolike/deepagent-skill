"""Application stdout logging configuration."""

# 日志只写 stdout 交由部署平台采集，格式化器不会主动序列化请求体或密钥。

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from config.settings import Settings
from core.request_context import request_id_var


_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|password|secret|token)(\s*[=:]\s*)([^\s,;]+)"
)
_SENSITIVE_KEY_PARTS = ("apikey", "authorization", "cookie", "password", "secret", "token")


class ApplicationFormatter(logging.Formatter):
    """Emit safe JSON or text logs with request correlation and optional tracebacks."""

    def __init__(self, json_output: bool, include_stacktrace: bool) -> None:
        super().__init__()
        self._json_output = json_output
        self._include_stacktrace = include_stacktrace

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update({key: _redact_value(value) for key, value in fields.items()})
        if record.exc_info:
            error_payload: dict[str, str] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] is not None else "UnknownError",
                "message": _redact_text(str(record.exc_info[1])) if record.exc_info[1] is not None else "",
            }
            if self._include_stacktrace:
                error_payload["stack_trace"] = _redact_text(self.formatException(record.exc_info))
            payload["error"] = error_payload
        if self._json_output:
            return json.dumps(payload, ensure_ascii=False, default=str)
        text = (
            f"{payload['timestamp']} {payload['level']} {payload['logger']} "
            f"request_id={payload['request_id']} [{payload['message']}]"
        )
        if fields:
            text = f"{text} fields={json.dumps(_redact_value(fields), ensure_ascii=False, default=str)}"
        if "error" in payload:
            text = f"{text} error_type={payload['error']['type']} error_message={payload['error']['message']}"
            if "stack_trace" in payload["error"]:
                text = f"{text}\n{payload['error']['stack_trace']}"
        return text


def _redact_value(value: Any) -> Any:
    """Mask nested credential-like fields before they reach any log formatter output."""
    if isinstance(value, dict):
        return {
            key: _redact_headers(item)
            if _is_header_container_key(key)
            else "***"
            if _is_sensitive_key(key)
            else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _is_sensitive_key(key: object) -> bool:
    """Recognize common credential field names across snake_case and HTTP-style keys."""
    normalized = re.sub(r"[_-]", "", str(key).lower())
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _is_header_container_key(key: object) -> bool:
    """Recognize a mapping that contains HTTP headers without exposing their values."""
    return "header" in re.sub(r"[_-]", "", str(key).lower())


def _redact_headers(value: Any) -> Any:
    """Retain diagnostic headers while masking only credential-bearing header values."""
    if isinstance(value, dict):
        return {key: "***" if _is_sensitive_key(key) else _redact_value(item) for key, item in value.items()}
    return "***"


def _redact_text(value: str) -> str:
    """Redact common key/value credential fragments that may appear in exception messages."""
    return _SENSITIVE_VALUE_PATTERN.sub(r"\1=***", value)


def configure_logging(settings: Settings) -> None:
    """Configure application logging exactly once during lifespan startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ApplicationFormatter(settings.log_format == "json", settings.log_include_stacktrace))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
