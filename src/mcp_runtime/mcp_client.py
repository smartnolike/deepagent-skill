"""Streamable HTTP MCP client with configured headers."""

# headers 可包含服务端 Token；本模块绝不记录 URL 参数、headers 或 MCP 调用参数。

import json
import logging
import ssl
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from config.mcp_server_settings import McpServerSettings
from mcp_runtime.tool_definition import McpToolDefinition


logger = logging.getLogger(__name__)


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
                verify=self._tls_verification_context(),
                trust_env=False,
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

    def _tls_verification_context(self) -> ssl.SSLContext:
        """Use system trust roots plus the configured private root CA, when present."""
        root_ca_path = self._settings.root_ca_path
        if root_ca_path is None:
            return ssl.create_default_context()
        resolved_path = Path(root_ca_path).resolve()
        if not resolved_path.is_file() or resolved_path.stat().st_size == 0:
            raise RuntimeError(f"MCP root certificate is missing or empty: {resolved_path}")
        # httpx 0.28 已弃用 verify="/path/to/ca.pem"。先加载系统根证书，再追加
        # 企业内部根证书，既能访问内部 MCP，也不会破坏公有 CA 的信任链。
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=str(resolved_path))
        return context

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
            logger.warning("mcp_raw_tool_error", extra={"fields": {"tool_name": tool_name}})
            raise RuntimeError("MCP tool reported an error")
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            logger.info(
                "mcp_tool_result_normalized",
                extra={
                    "fields": {
                        "tool_name": tool_name,
                        "source": "structuredContent",
                        "top_level_keys": sorted(str(key) for key in structured.keys()),
                    }
                },
            )
            return structured
        content = getattr(result, "content", [])
        for index, item in enumerate(content):
            text = getattr(item, "text", None)
            if text:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    logger.info(
                        "mcp_tool_result_normalized",
                        extra={
                            "fields": {
                                "tool_name": tool_name,
                                "source": "content_text_json",
                                "content_index": index,
                                "top_level_keys": sorted(str(key) for key in parsed.keys()),
                            }
                        },
                    )
                    return parsed
                logger.warning(
                    "mcp_tool_text_result_not_object",
                    extra={
                        "fields": {
                            "tool_name": tool_name,
                            "content_index": index,
                            "parsed_type": type(parsed).__name__,
                        }
                    },
                )
        logger.warning(
            "mcp_tool_result_missing_object",
            extra={"fields": {"tool_name": tool_name, "content_item_count": len(content)}},
        )
        raise RuntimeError("MCP tool returned no object result")

    async def close(self) -> None:
        """Close the SDK transport and session."""
        await self._stack.aclose()
