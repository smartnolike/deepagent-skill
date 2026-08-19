"""Streamable HTTP MCP client with configured headers."""

# headers 可包含服务端 Token；本模块绝不记录 URL 参数、headers 或 MCP 调用参数。

import json
from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from config.mcp_server_settings import McpServerSettings
from mcp_runtime.tool_definition import McpToolDefinition


class McpClient:
    """Long-lived MCP SDK session for one Streamable HTTP MCP server."""

    def __init__(self, settings: McpServerSettings) -> None:
        self._settings = settings
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def connect(self) -> None:
        """Open and initialize a Streamable HTTP MCP session with configured headers."""
        if self._settings.url is None:
            raise ValueError("HTTP MCP server requires url")
        # 新版 MCP SDK 通过调用方提供的 httpx client 接收 headers 和 timeout。
        # 将 client 纳入同一个 ExitStack，重连和应用关闭时会一并释放连接池。
        http_client = await self._stack.enter_async_context(
            httpx.AsyncClient(
                headers=self._settings.headers,
                timeout=self._settings.timeout_seconds,
            )
        )
        read_stream, write_stream, _ = await self._stack.enter_async_context(
            streamable_http_client(
                str(self._settings.url),
                http_client=http_client,
            )
        )
        self._session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self._session.initialize()

    async def list_tools(self) -> list[McpToolDefinition]:
        """Read the server-owned Tool schemas used to register LangChain Tools."""
        if self._session is None:
            raise ConnectionError("MCP session is not connected")
        definitions: list[McpToolDefinition] = []
        cursor: str | None = None
        while True:
            response = await self._session.list_tools(cursor=cursor)
            definitions.extend(
                McpToolDefinition(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema,
                )
                for tool in response.tools
            )
            cursor = response.nextCursor
            if cursor is None:
                return definitions

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke an MCP Tool with its business arguments and normalize its result."""
        if self._session is None:
            raise ConnectionError("MCP session is not connected")
        # MCP SDK 负责包成 JSON-RPC 的 params.arguments；arguments 本身必须保持业务字段扁平。
        result = await self._session.call_tool(tool_name, arguments)
        if getattr(result, "isError", False):
            raise RuntimeError("MCP tool reported an error")
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured
        content = getattr(result, "content", [])
        for item in content:
            text = getattr(item, "text", None)
            if text:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
        raise RuntimeError("MCP tool returned no object result")

    async def close(self) -> None:
        """Close the SDK transport and session."""
        await self._stack.aclose()
