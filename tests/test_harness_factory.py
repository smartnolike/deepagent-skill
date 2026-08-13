"""DeepAgent harness factory tests."""

# 未配置真实模型时必须保持可运行的 Mock harness，便于本地回归测试。

from src.agent.harness_service import DeepAgentHarnessService
from src.agent.factory import create_agent_service
from src.config.settings import Settings
from src.mcp.manager import McpClientManager
from src.services.memory_service import MemoryService
from langgraph.store.memory import InMemoryStore


def test_factory_uses_mock_harness_without_model() -> None:
    settings = Settings.model_validate(
        {
            "app_env": "local",
            "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
            "api_auth_token": "x",
            "mcp_servers": {"ticketing": {"transport": "mock", "tools": []}},
        }
    )
    assert isinstance(
        create_agent_service(settings, McpClientManager(settings), MemoryService(InMemoryStore())),
        DeepAgentHarnessService,
    )
