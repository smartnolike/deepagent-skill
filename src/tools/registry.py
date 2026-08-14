"""将应用自定义 Tool 注册给根 DeepAgent。"""

# 自定义 Tool 与 MCP Tool 分开注册，方便审计其网络访问和权限边界。

from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config.tool_settings import ToolSettings
from src.common.httpx_client import HttpxClient
from src.tools.echo import echo_text
from src.tools.external_status import get_configured_service_status
from src.tools.danaan_template import get_danaan_resource_template
from src.tools.skill_memory import create_get_skill_memory_tool
from src.tools.user_form import request_user_form
from src.services.memory_service import MemoryService


class CustomToolRegistry:
    """根据 YAML 配置构建可供 Agent 使用的应用内 Tool。"""

    def __init__(
        self,
        settings: ToolSettings,
        client: HttpxClient | None,
        session_factory: async_sessionmaker[AsyncSession] | None,
        memory_service: MemoryService,
    ) -> None:
        self._settings = settings
        self._client = client
        self._session_factory = session_factory
        self._memory_service = memory_service

    def build(self) -> list[StructuredTool]:
        """仅在外部状态 API 已显式配置时注册示例 Tool。"""
        # 无依赖 Tool 可直接注册；依赖 HTTP client 的 Tool 则按 YAML 开关注册。
        tools: list[StructuredTool] = [echo_text, request_user_form, create_get_skill_memory_tool(self._memory_service)]
        if self._session_factory is not None:
            async def get_template(resource_name: str) -> str:
                return await get_danaan_resource_template(self._session_factory, resource_name)

            tools.append(
                StructuredTool.from_function(
                    coroutine=get_template,
                    name="danaan_get_resource_template",
                    description="Read the latest Danaan resourceContent template by resourceName.",
                )
            )
        if self._client is None or self._settings.external_status_url is None:
            return tools

        async def invoke() -> str:
            return await get_configured_service_status(self._client, str(self._settings.external_status_url))

        tools.append(
            StructuredTool.from_function(
                coroutine=invoke,
                name="get_configured_service_status",
                description="Read JSON service status from the configured allowlisted external endpoint.",
            )
        )
        return tools
