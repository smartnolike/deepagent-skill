"""Shared test application fixture."""

# 测试使用独立 SQLite 文件和 InMemoryStore，避免依赖真实 PostgreSQL、模型或 MCP 服务。

import asyncio

import pytest
from fastapi.testclient import TestClient

from config.settings import Settings
from database.base import Base
import main as main_module
from main import create_app

from fake_agent_service import FakeAgentService
from test_values import TEST_API_KEY, TEST_AUTH_TOKEN, TEST_PASSWORD


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Inject an Agent fake at the application boundary; production has no mock harness."""
    monkeypatch.setattr(main_module, "create_agent_service", lambda *_args, **_kwargs: FakeAgentService())
    settings = Settings.model_validate(
        {
            "agent_env": "local",
            "database": {"host": "localhost", "name": "deepagent", "user": "postgres", "password": TEST_PASSWORD},
            "api_auth_token": TEST_AUTH_TOKEN,
            "agent": {"provider": "openai", "model": "test-model", "api_key": TEST_API_KEY},
            "mcp_servers": {},
        }
    )
    app = create_app(settings, f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as test_client:
        async def prepare() -> None:
            async with app.state.engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

        asyncio.run(prepare())
        yield test_client
