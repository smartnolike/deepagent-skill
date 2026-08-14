"""Shared test application fixture."""

# 测试使用独立 SQLite 文件和 InMemoryStore，避免依赖真实 PostgreSQL、模型或 MCP 服务。

import asyncio

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.database.base import Base
from src.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings.model_validate(
        {
            "app_env": "local",
            "allow_test_doubles": True,
            "database": {"host": "localhost", "name": "deepagent", "user": "postgres", "password": "postgres"},
            "api_auth_token": "test-token",
            "mcp_servers": {
                "ticketing": {
                    "transport": "mock",
                    "tools": ["get_resource_schema", "validate_ticket_params", "create_ticket"],
                    "confirmation_required_tools": ["create_ticket"],
                }
            },
        }
    )
    app = create_app(settings, f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as test_client:
        async def prepare() -> None:
            async with app.state.engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

        asyncio.run(prepare())
        yield test_client
