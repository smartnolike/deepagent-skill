"""Read one Danaan cloud-resource JSON Schema from its configured API."""

# 基础 URL 由 YAML 控制；模型只能提供 resourceVersion 作为单一路径段，不能指定任意请求地址。

import json
import logging
import time
from urllib.parse import quote

from common.httpx_client import HttpxClient

logger = logging.getLogger(__name__)


async def get_danaan_json_schema(client: HttpxClient, base_url: str, resourceVersion: str) -> str:
    """Fetch the JSON Schema for one Danaan ``resourceVersion`` by HTTP GET."""
    normalized_version = resourceVersion.strip()
    if not normalized_version:
        logger.warning("danaan_json_schema_rejected reason=empty_resource_version")
        raise ValueError("resourceVersion must not be empty")
    if len(normalized_version) > 128:
        logger.warning(
            "danaan_json_schema_rejected",
            extra={
                "fields": {
                    "reason": "resource_version_too_long",
                    "resource_version": normalized_version,
                }
            },
        )
        raise ValueError("resourceVersion must be at most 128 characters")
    # quote 将用户/模型输入限制为一个 URL path segment，不能借此改变 YAML allowlisted host。
    url = f"{base_url.rstrip('/')}/{quote(normalized_version, safe='')}"
    started = time.perf_counter()
    logger.info(
        "danaan_json_schema_requested",
        extra={"fields": {"resource_version": normalized_version}},
    )
    try:
        result = await client.get_json(url)
    except Exception as exc:
        logger.exception(
            "danaan_json_schema_failed",
            extra={
                "fields": {
                    "resource_version": normalized_version,
                    "error_type": type(exc).__name__,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                }
            },
        )
        raise
    logger.info(
        "danaan_json_schema_completed",
        extra={
            "fields": {
                "resource_version": normalized_version,
                "result": result,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        },
    )
    return json.dumps(result, ensure_ascii=False)
