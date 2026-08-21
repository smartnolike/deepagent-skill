"""Read one Danaan cloud-resource JSON Schema from its configured API."""

# 基础 URL 由 YAML 控制；模型只能提供 resourceVersion 作为单一路径段，不能指定任意请求地址。

import json
from urllib.parse import quote

from common.httpx_client import HttpxClient


async def get_danaan_json_schema(client: HttpxClient, base_url: str, resourceVersion: str) -> str:
    """Fetch the JSON Schema for one Danaan ``resourceVersion`` by HTTP GET."""
    normalized_version = resourceVersion.strip()
    if not normalized_version:
        raise ValueError("resourceVersion must not be empty")
    if len(normalized_version) > 128:
        raise ValueError("resourceVersion must be at most 128 characters")
    # quote 将用户/模型输入限制为一个 URL path segment，不能借此改变 YAML allowlisted host。
    url = f"{base_url.rstrip('/')}/{quote(normalized_version, safe='')}"
    return json.dumps(await client.get_json(url), ensure_ascii=False)
