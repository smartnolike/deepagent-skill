"""Small stdout logging setup."""

# 日志只写 stdout 交由部署平台采集，格式化器不会主动序列化请求体或密钥。

import json
import logging
import sys
from datetime import UTC, datetime

from src.config.settings import Settings
from src.core.request_context import request_id_var


class JsonFormatter(logging.Formatter):
    """Emit minimal structured JSON logs with the request correlation ID."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: Settings) -> None:
    """Configure application logging exactly once during lifespan startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_format == "json" else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(message)s]"
    ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
