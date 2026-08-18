"""MCP connection manager with startup Tool discovery and runtime reconnects."""

# 启动时从 MCP Server 获取真实 inputSchema；运行期只重连 Session，不动态改变 Agent 的 Tool 契约。

import asyncio
import logging
import time
from collections.abc import Sequence
from typing import Any

import httpx

from src.config.settings import Settings
from src.mcp.mcp_client import McpClient
from src.mcp.tool_definition import McpToolDefinition

_RECONNECTABLE_ERRORS = (ConnectionError, TimeoutError, OSError, httpx.HTTPError)


class McpClientManager:
    """Own MCP sessions, validate startup Tool contracts, and reconnect failed sessions once."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._clients: dict[str, McpClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._tool_definitions: dict[str, tuple[McpToolDefinition, ...]] = {}
        self._logger = logging.getLogger(__name__)

    @property
    def server_settings(self):
        """Return enabled MCP Servers; disabled Servers are neither connected nor exposed."""
        return {
            server_id: server
            for server_id, server in self._settings.mcp_servers.items()
            if server.enabled
        }

    @property
    def tool_definitions(self) -> dict[str, tuple[McpToolDefinition, ...]]:
        """Return startup-discovered, allowlisted Tool contracts keyed by server ID."""
        return self._tool_definitions.copy()

    async def start(self) -> None:
        """Connect every enabled server and discover its real, allowlisted Tool schemas."""
        for server_id in self.server_settings:
            self._locks[server_id] = asyncio.Lock()
        try:
            for server_id in self.server_settings:
                await self._connect_and_discover(server_id, startup=True)
        except Exception:
            await self.close()
            raise
        self._logger.info(
            "mcp_manager_initialized",
            extra={
                "fields": {
                    "server_count": len(self._clients),
                    "tool_count": sum(len(tools) for tools in self._tool_definitions.values()),
                }
            },
        )

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a discovered Tool; reconnect its server and retry the original request once on transport failure."""
        started = time.perf_counter()
        server_id, tool_name = qualified_name.split("__", maxsplit=1)
        if not self._is_allowlisted_tool(server_id, tool_name):
            self._logger.warning("mcp_tool_rejected server_id=%s tool_name=%s", server_id, tool_name)
            raise RuntimeError("MCP_UNAVAILABLE")
        client = self._client_for(server_id)
        try:
            result = await client.call_tool(tool_name, arguments)
        except _RECONNECTABLE_ERRORS as exc:
            self._logger.warning(
                "mcp_tool_connection_failed_reconnecting",
                extra={"fields": {"server_id": server_id, "tool_name": tool_name, "error_type": type(exc).__name__}},
            )
            try:
                await self._reconnect(server_id, client)
                result = await self._client_for(server_id).call_tool(tool_name, arguments)
            except Exception as retry_exc:
                self._logger.exception(
                    "mcp_tool_retry_failed",
                    extra={
                        "fields": {
                            "server_id": server_id,
                            "tool_name": tool_name,
                            "error_type": type(retry_exc).__name__,
                            "duration_ms": int((time.perf_counter() - started) * 1000),
                        }
                    },
                )
                raise RuntimeError("MCP_UNAVAILABLE") from retry_exc
        except Exception as exc:
            self._logger.exception(
                "mcp_tool_failed",
                extra={
                    "fields": {
                        "server_id": server_id,
                        "tool_name": tool_name,
                        "error_type": type(exc).__name__,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                    }
                },
            )
            raise RuntimeError("MCP_TOOL_FAILED") from exc
        self._logger.info(
            "mcp_tool_completed",
            extra={
                "fields": {
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                }
            },
        )
        return result

    async def close(self) -> None:
        """Close every active MCP client."""
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.close()
        self._logger.info("mcp_manager_closed")

    def _is_allowlisted_tool(self, server_id: str, tool_name: str) -> bool:
        """Ensure only startup-discovered Tool names can be called."""
        return tool_name in {definition.name for definition in self._tool_definitions.get(server_id, ())}

    def _client_for(self, server_id: str) -> McpClient:
        """Return the established client or surface a controlled availability error."""
        client = self._clients.get(server_id)
        if client is None:
            raise ConnectionError(f"MCP client is unavailable: {server_id}")
        return client

    async def _reconnect(self, server_id: str, failed_client: McpClient) -> None:
        """Replace one failed Session and validate that its allowlisted Tool names remain available."""
        lock = self._locks[server_id]
        async with lock:
            # 其他协程可能已经成功替换了相同的失效 Session；此时复用新连接即可。
            if self._clients.get(server_id) is not failed_client:
                return
            await self._disconnect(server_id)
            await self._connect_and_discover(server_id, startup=False)

    async def _connect_and_discover(self, server_id: str, *, startup: bool) -> None:
        """Connect one server, discover schemas, and retain the startup Tool contract."""
        started = time.perf_counter()
        client = self._create_client(server_id)
        try:
            await client.connect()
            definitions = tuple(await client.list_tools())
            allowlisted = self._allowlisted_definitions(server_id, definitions)
            previous = self._tool_definitions.get(server_id)
            if previous is not None and previous != allowlisted:
                self._logger.warning(
                    "mcp_tool_schema_changed_restart_required",
                    extra={"fields": {"server_id": server_id, "tool_count": len(allowlisted)}},
                )
            else:
                self._tool_definitions[server_id] = allowlisted
            self._clients[server_id] = client
        except Exception:
            await client.close()
            raise
        self._logger.info(
            "mcp_connected_and_discovered",
            extra={
                "fields": {
                    "server_id": server_id,
                    "startup": startup,
                    "tool_count": len(self._tool_definitions[server_id]),
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                }
            },
        )

    def _create_client(self, server_id: str) -> McpClient:
        """Create a transport-specific client without storing it before successful discovery."""
        server = self.server_settings[server_id]
        if server.transport == "http":
            return McpClient(server)
        raise RuntimeError(f"Unsupported MCP transport: {server.transport}")

    def _allowlisted_definitions(
        self, server_id: str, definitions: Sequence[McpToolDefinition]
    ) -> tuple[McpToolDefinition, ...]:
        """Filter server discovery by YAML and fail startup when configured Tools are absent."""
        configured_names = self.server_settings[server_id].tools
        available = {definition.name: definition for definition in definitions}
        missing = sorted(set(configured_names) - set(available))
        if missing:
            raise RuntimeError(f"MCP server {server_id} does not expose allowlisted tools: {', '.join(missing)}")
        return tuple(available[name] for name in configured_names)

    async def _disconnect(self, server_id: str) -> None:
        """Discard and close one failed MCP client."""
        client = self._clients.pop(server_id, None)
        if client is not None:
            await client.close()
