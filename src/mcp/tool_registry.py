"""LangChain Tool registration for namespaced MCP capabilities."""

# 将 MCP 工具映射为 server_id__tool_name，避免多个 Server 的工具同名。

import json
from typing import Any

from langchain_core.tools import StructuredTool

from src.mcp.manager import McpClientManager


class McpToolRegistry:
    """Expose each configured MCP allowlisted tool to the root DeepAgent."""

    def __init__(self, manager: McpClientManager) -> None:
        self._manager = manager

    def build(self) -> list[StructuredTool]:
        """Create namespaced async LangChain tools from the MCP configuration."""
        tools: list[StructuredTool] = []
        for server_id, server in self._manager.server_settings.items():
            for tool_name in server.tools:
                qualified_name = f"{server_id}__{tool_name}"
                tools.append(
                    StructuredTool.from_function(
                        coroutine=self._tool_callable(qualified_name),
                        name=qualified_name,
                        description=f"Call MCP tool {tool_name} on configured server {server_id}.",
                    )
                )
        return tools

    def _tool_callable(self, qualified_name: str):
        async def invoke(**arguments: Any) -> str:
            result = await self._manager.call_tool(qualified_name, arguments)
            return json.dumps(result, ensure_ascii=False)

        return invoke
