"""MCP connection manager with lazy reconnects."""

# 每个 MCP Server 独立管理连接与重连，单个服务故障不会阻塞其他 MCP。

import asyncio
import logging
from typing import Any

from src.config.settings import Settings
from src.mcp.http_client import HttpMcpClient
from src.mcp.mock_client import MockMcpClient


class McpClientManager:
    """Own configured MCP clients and isolate server failures."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._clients: dict[str, MockMcpClient | HttpMcpClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._logger = logging.getLogger(__name__)

    @property
    def server_settings(self):
        """Return configured MCP server settings for tool registration."""
        return self._settings.mcp_servers

    async def start(self) -> None:
        """Initialize mock clients; remote transports connect lazily on first tool use."""
        for server_id, server in self._settings.mcp_servers.items():
            if server.transport == "mock":
                self._clients[server_id] = MockMcpClient()
            self._locks[server_id] = asyncio.Lock()

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a configured, namespaced tool and reconnect the server if needed."""
        server_id, tool_name = qualified_name.split("__", maxsplit=1)
        server = self._settings.mcp_servers.get(server_id)
        if not server or tool_name not in server.tools:
            self._logger.warning("mcp_tool_rejected server_id=%s tool_name=%s", server_id, tool_name)
            raise RuntimeError("MCP_UNAVAILABLE")
        client = await self._get_client(server_id)
        try:
            self._logger.info("mcp_tool_started server_id=%s tool_name=%s", server_id, tool_name)
            result = await client.call_tool(tool_name, arguments)
            self._logger.info("mcp_tool_completed server_id=%s tool_name=%s", server_id, tool_name)
            return result
        except (ConnectionError, TimeoutError):
            self._logger.warning("mcp_tool_disconnected server_id=%s tool_name=%s", server_id, tool_name)
            await self._disconnect(server_id)
            if tool_name == "create_ticket":
                raise RuntimeError("MCP_UNAVAILABLE")
            client = await self._get_client(server_id)
            result = await client.call_tool(tool_name, arguments)
            self._logger.info("mcp_tool_completed_after_reconnect server_id=%s tool_name=%s", server_id, tool_name)
            return result

    async def close(self) -> None:
        """Close every active MCP client."""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
        self._logger.info("mcp_manager_closed")

    async def _get_client(self, server_id: str) -> MockMcpClient | HttpMcpClient:
        client = self._clients.get(server_id)
        if client:
            return client
        async with self._locks[server_id]:
            if server_id not in self._clients:
                server = self._settings.mcp_servers[server_id]
                if server.transport == "mock":
                    self._clients[server_id] = MockMcpClient()
                elif server.transport == "http":
                    client = HttpMcpClient(server)
                    await client.connect()
                    self._clients[server_id] = client
                else:
                    raise RuntimeError("MCP_UNAVAILABLE")
                self._logger.info("mcp_reconnected server_id=%s", server_id)
            return self._clients[server_id]

    async def _disconnect(self, server_id: str) -> None:
        client = self._clients.pop(server_id, None)
        if client:
            await client.close()
