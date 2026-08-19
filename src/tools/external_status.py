"""读取受控外部服务状态的示例 Tool。"""

# 示例 Tool 没有 URL 输入参数，调用目标完全来自 YAML allowlist，避免模型触发任意外部请求。

import json

from common.httpx_client import HttpxClient


async def get_configured_service_status(client: HttpxClient, url: str) -> str:
    """调用 YAML 指定的状态接口并返回 JSON 字符串。"""
    return json.dumps(await client.get_json(url), ensure_ascii=False)
