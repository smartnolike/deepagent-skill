"""MCP startup discovery and reconnect tests."""

import pytest

from src.config.settings import Settings
from src.mcp import manager as manager_module
from src.mcp.manager import McpClientManager
from src.mcp.tool_definition import McpToolDefinition
from src.mcp.tool_registry import McpToolRegistry


class FakeMcpClient:
    """HTTP MCP test double with one real-shaped Tool schema per Session."""

    instances: list["FakeMcpClient"] = []

    def __init__(self, settings) -> None:
        self.settings = settings
        self.connect_calls = 0
        self.list_tools_calls = 0
        self.close_calls = 0
        self.tool_calls: list[tuple[str, dict[str, object]]] = []
        self.fail_next_tool_call = len(self.instances) == 0
        self.instances.append(self)

    async def connect(self) -> None:
        self.connect_calls += 1

    async def list_tools(self) -> list[McpToolDefinition]:
        self.list_tools_calls += 1
        return [
            McpToolDefinition(
                name="search",
                description="Search knowledge.",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.tool_calls.append((tool_name, arguments))
        if self.fail_next_tool_call:
            self.fail_next_tool_call = False
            raise ConnectionError("expired MCP session")
        return {"status": "ok"}

    async def close(self) -> None:
        self.close_calls += 1


def _settings(*, tools: list[str] | None = None) -> Settings:
    """Create minimal settings with one enabled HTTP MCP server."""
    return Settings.model_validate(
        {
            "agent_env": "local",
            "allow_test_doubles": True,
            "database": {"host": "localhost", "name": "deepagent", "user": "postgres", "password": "postgres"},
            "api_auth_token": "test-token",
            "mcp_servers": {
                "knowledge": {
                    "transport": "http",
                    "url": "https://mcp.example.internal/api",
                    "tools": tools if tools is not None else ["search"],
                }
            },
        }
    )


@pytest.mark.asyncio
async def test_http_mcp_is_connected_and_discovered_during_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabled MCP servers must expose their allowlisted Tool schemas before Agent creation."""
    FakeMcpClient.instances.clear()
    monkeypatch.setattr(manager_module, "McpClient", FakeMcpClient)
    manager = McpClientManager(_settings())

    await manager.start()

    assert len(FakeMcpClient.instances) == 1
    client = FakeMcpClient.instances[0]
    assert client.connect_calls == 1
    assert client.list_tools_calls == 1
    assert manager.tool_definitions["knowledge"][0].input_schema["required"] == ["query"]
    await manager.close()


@pytest.mark.asyncio
async def test_registry_uses_real_mcp_schema_without_nested_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model receives business fields directly, rather than a synthetic ``arguments`` property."""
    FakeMcpClient.instances.clear()
    monkeypatch.setattr(manager_module, "McpClient", FakeMcpClient)
    manager = McpClientManager(_settings())
    await manager.start()

    tool = McpToolRegistry(manager).build()[0]

    assert tool.args_schema == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    assert "arguments" not in tool.args
    FakeMcpClient.instances[0].fail_next_tool_call = False
    await tool.ainvoke({"query": "test"})
    assert FakeMcpClient.instances[0].tool_calls == [("search", {"query": "test"})]
    await manager.close()


@pytest.mark.asyncio
async def test_connection_failure_reconnects_and_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A restarted MCP session is replaced and the same Tool call is retried once."""
    FakeMcpClient.instances.clear()
    monkeypatch.setattr(manager_module, "McpClient", FakeMcpClient)
    manager = McpClientManager(_settings())
    await manager.start()

    result = await manager.call_tool("knowledge__search", {"query": "test"})

    assert result == {"status": "ok"}
    assert len(FakeMcpClient.instances) == 2
    first, second = FakeMcpClient.instances
    assert first.close_calls == 1
    assert second.connect_calls == 1
    assert second.tool_calls == [("search", {"query": "test"})]
    await manager.close()


@pytest.mark.asyncio
async def test_startup_fails_when_allowlisted_tool_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured Tool missing from MCP discovery must block Agent startup."""
    FakeMcpClient.instances.clear()
    monkeypatch.setattr(manager_module, "McpClient", FakeMcpClient)
    manager = McpClientManager(_settings(tools=["missing_tool"]))

    with pytest.raises(RuntimeError, match="does not expose allowlisted tools"):
        await manager.start()
