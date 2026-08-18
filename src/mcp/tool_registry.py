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
        """Create namespaced Tools using the MCP Server's real input schemas."""
        tools: list[StructuredTool] = []
        for server_id, definitions in self._manager.tool_definitions.items():
            for definition in definitions:
                qualified_name = f"{server_id}__{definition.name}"
                tools.append(
                    StructuredTool(
                        coroutine=self._tool_callable(qualified_name),
                        name=qualified_name,
                        description=definition.description,
                        # 直接使用 MCP inputSchema，避免 **arguments 被推断成同名嵌套字段。
                        args_schema=definition.input_schema,
                    )
                )
        return tools

    def _tool_callable(self, qualified_name: str):
        async def invoke(**arguments: Any) -> str:
            result = await self._manager.call_tool(qualified_name, arguments)
            return json.dumps(result, ensure_ascii=False)

        return invoke
