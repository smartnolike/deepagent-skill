"""MCP manager lazy-connection tests."""

# 验证可选 MCP 不阻塞应用启动，且只在 Agent 实际调用对应 Tool 时建立 Session。

import pytest

from src.config.settings import Settings
from src.mcp import manager as manager_module
from src.mcp.manager import McpClientManager


class FakeHttpMcpClient:
    """记录连接与调用次数的 HTTP MCP 测试替身。"""

    instances: list["FakeHttpMcpClient"] = []

    def __init__(self, settings) -> None:
        self.settings = settings
        self.connect_calls = 0
        self.close_calls = 0
        self.tool_calls: list[tuple[str, dict[str, object]]] = []
        self.instances.append(self)

    async def connect(self) -> None:
        self.connect_calls += 1

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.tool_calls.append((tool_name, arguments))
        return {"status": "ok"}

    async def close(self) -> None:
        self.close_calls += 1


def _settings() -> Settings:
    """创建包含一个 HTTP MCP 的最小测试配置。"""
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
                    "tools": ["search"],
                }
            },
        }
    )


@pytest.mark.asyncio
async def test_http_mcp_connection_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    """start 只完成初始化，首次 Tool 调用才创建和连接 HTTP client。"""
    FakeHttpMcpClient.instances.clear()
    monkeypatch.setattr(manager_module, "HttpMcpClient", FakeHttpMcpClient)
    manager = McpClientManager(_settings())

    await manager.start()

    assert FakeHttpMcpClient.instances == []

    result = await manager.call_tool("knowledge__search", {"query": "test"})

    assert result == {"status": "ok"}
    assert len(FakeHttpMcpClient.instances) == 1
    client = FakeHttpMcpClient.instances[0]
    assert client.connect_calls == 1
    assert client.tool_calls == [("search", {"query": "test"})]

    await manager.close()

    assert client.close_calls == 1
