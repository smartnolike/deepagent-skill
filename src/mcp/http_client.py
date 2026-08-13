"""Streamable HTTP MCP client with configured headers."""

# headers 可包含服务端 Token；本模块绝不记录 URL 参数、headers 或 MCP 调用参数。

import json
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from src.config.mcp_server_settings import McpServerSettings


class HttpMcpClient:
    """Long-lived MCP SDK session for one HTTP MCP server."""

    def __init__(self, settings: McpServerSettings) -> None:
        self._settings = settings
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def connect(self) -> None:
        """Open and initialize a Streamable HTTP MCP session with configured headers."""
        if self._settings.url is None:
            raise ValueError("HTTP MCP server requires url")
        read_stream, write_stream, _ = await self._stack.enter_async_context(
            streamablehttp_client(
                str(self._settings.url),
                headers=self._settings.headers,
                timeout=self._settings.timeout_seconds,
            )
        )
        self._session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self._session.initialize()

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke an MCP tool and normalize structured or JSON text results."""
        if self._session is None:
            raise ConnectionError("MCP session is not connected")
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
