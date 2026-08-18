"""MCP startup discovery and reconnect tests."""

import pytest
from types import SimpleNamespace

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
            ),
            McpToolDefinition(
                name="external_resource_add",
                description="Create a Danaan resource request.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "body": {
                            "type": "object",
                            "properties": {
                                "applicationName": {"type": "string"},
                                "creator": {"type": "string"},
                                "creatorName": {"type": "string"},
                                "creatorEmail": {"type": "string"},
                            },
                            "required": ["applicationName", "creator", "creatorName", "creatorEmail"],
                        }
                    },
                    "required": ["body"],
                },
            ),
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.tool_calls.append((tool_name, arguments))
        if self.fail_next_tool_call:
            self.fail_next_tool_call = False
            raise ConnectionError("expired MCP session")
        return {"status": "ok"}

    async def close(self) -> None:
        self.close_calls += 1


def _settings(
    *,
    tools: list[str] | None = None,
    context_argument_bindings: dict[str, dict[str, str]] | None = None,
    fixed_arguments: dict[str, dict[str, str]] | None = None,
) -> Settings:
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
                    "context_argument_bindings": context_argument_bindings or {},
                    "fixed_arguments": fixed_arguments or {},
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
async def test_registry_hides_and_overrides_system_context_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """System identity fields must be hidden from the model and force-injected at Tool execution."""
    FakeMcpClient.instances.clear()
    monkeypatch.setattr(manager_module, "McpClient", FakeMcpClient)
    manager = McpClientManager(
        _settings(
            tools=["external_resource_add"],
            context_argument_bindings={"external_resource_add": {"body.creator": "staff_id"}},
            fixed_arguments={
                "external_resource_add": {
                    "body.creatorName": "",
                    "body.creatorEmail": "",
                }
            },
        )
    )
    await manager.start()
    tool = McpToolRegistry(manager).build()[0]

    body_schema = tool.args_schema["properties"]["body"]
    assert set(body_schema["properties"]) == {"applicationName"}
    assert body_schema["required"] == ["applicationName"]

    FakeMcpClient.instances[0].fail_next_tool_call = False
    await tool.coroutine(  # type: ignore[misc]
        runtime=SimpleNamespace(context={"staff_id": "staff-123", "conversation_id": "conversation-123"}),
        body={"applicationName": "payments", "creator": "spoofed"},
    )

    assert FakeMcpClient.instances[0].tool_calls == [
        (
            "external_resource_add",
            {
                "body": {
                    "applicationName": "payments",
                    "creator": "staff-123",
                    "creatorName": "",
                    "creatorEmail": "",
                }
            },
        )
    ]
    await manager.close()


@pytest.mark.asyncio
async def test_startup_fails_when_allowlisted_tool_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured Tool missing from MCP discovery must block Agent startup."""
    FakeMcpClient.instances.clear()
    monkeypatch.setattr(manager_module, "McpClient", FakeMcpClient)
    manager = McpClientManager(_settings(tools=["missing_tool"]))

    with pytest.raises(RuntimeError, match="does not expose allowlisted tools"):
        await manager.start()
