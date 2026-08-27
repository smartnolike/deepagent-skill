"""将应用自定义 Tool 注册给根 DeepAgent。"""

# 自定义 Tool 与 MCP Tool 分开注册，方便审计其网络访问和权限边界。

from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.tool_settings import ToolSettings
from common.httpx_client import HttpxClient
from tools.danaan_json_schema import get_danaan_json_schema
from tools.danaan_template import get_danaan_resource_template
from tools.skill_memory import create_get_skill_memory_tool
from tools.user_form import request_user_form
from services.memory_service import MemoryService
from sandbox.workspace_manager import WorkspaceManager
from tools.workspace_artifact import create_publish_artifact_tool


class CustomToolRegistry:
    """根据 YAML 配置构建可供 Agent 使用的应用内 Tool。"""

    def __init__(
        self,
        settings: ToolSettings,
        client: HttpxClient | None,
        session_factory: async_sessionmaker[AsyncSession] | None,
        memory_service: MemoryService,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._session_factory = session_factory
        self._memory_service = memory_service
        self._workspace_manager = workspace_manager

    def build(self) -> list[StructuredTool]:
        """Build application Tools, registering the schema reader only when its endpoint is configured."""
        tools: list[StructuredTool] = [
            request_user_form,
            create_get_skill_memory_tool(self._memory_service),
        ]
        if (
            self._session_factory is not None
            and self._workspace_manager is not None
            and self._workspace_manager.supports_artifacts
        ):
            tools.append(create_publish_artifact_tool(self._session_factory, self._workspace_manager))
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
        if self._client is None or self._settings.danaan_json_schema_url is None:
            return tools

        async def invoke_danaan_json_schema(resourceVersion: str) -> str:
            return await get_danaan_json_schema(
                self._client,
                str(self._settings.danaan_json_schema_url),
                resourceVersion,
            )

        tools.append(
            StructuredTool.from_function(
                coroutine=invoke_danaan_json_schema,
                name="danaan_json_schema",
                description="Read the Danaan cloud-resource JSON Schema for a resourceVersion from the configured allowlisted API.",
            )
        )
        return tools
