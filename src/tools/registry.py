"""将应用自定义 Tool 注册给根 DeepAgent。"""

# 自定义 Tool 与 MCP Tool 分开注册，方便审计其网络访问和权限边界。

from langchain_core.tools import StructuredTool

from src.config.tool_settings import ToolSettings
from src.core.http_client import ExternalHttpClient
from src.tools.external_status import get_configured_service_status


class CustomToolRegistry:
    """根据 YAML 配置构建可供 Agent 使用的应用内 Tool。"""

    def __init__(self, settings: ToolSettings, client: ExternalHttpClient | None) -> None:
        self._settings = settings
        self._client = client

    def build(self) -> list[StructuredTool]:
        """仅在外部状态 API 已显式配置时注册示例 Tool。"""
        if self._client is None or self._settings.external_status_url is None:
            return []

        async def invoke() -> str:
            return await get_configured_service_status(self._client, str(self._settings.external_status_url))

        return [
            StructuredTool.from_function(
                coroutine=invoke,
                name="get_configured_service_status",
                description="读取配置中允许访问的外部服务状态 JSON。",
            )
        ]
