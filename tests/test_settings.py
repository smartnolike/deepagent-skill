"""Settings validation tests."""

# 覆盖 YAML 环境变量展开及不同环境下数据库认证规则。

import pytest
from pydantic import ValidationError

from src.config.load_settings import load_settings
from src.config.settings import Settings


def test_local_requires_password() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {"app_env": "local", "database": {"host": "x", "name": "x", "user": "x"}, "api_auth_token": "x", "mcp_servers": {}}
        )


def test_dev_allows_no_password() -> None:
    settings = Settings.model_validate(
        {"app_env": "dev", "database": {"host": "x", "name": "x", "user": "x"}, "api_auth_token": "x", "mcp_servers": {}}
    )
    assert settings.database.password is None


def test_agent_skill_configuration_defaults_to_mock_harness() -> None:
    settings = Settings.model_validate(
        {"app_env": "local", "database": {"host": "x", "name": "x", "user": "x", "password": "x"}, "api_auth_token": "x", "mcp_servers": {}}
    )
    assert settings.agent.model is None


def test_yaml_expands_environment_references(tmp_path, monkeypatch) -> None:
    (tmp_path / "local.yaml").write_text(
        """app_env: local
database: {host: localhost, name: deepagent, user: postgres, password: "${DB_PASSWORD}"}
api_auth_token: "${API_TOKEN:-fallback-token}"
mcp_servers:
  ticketing:
    transport: mock
    headers: {Authorization: 'Bearer ${MCP_TOKEN}'}
    tools: []
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DB_PASSWORD", "postgres")
    monkeypatch.setenv("MCP_TOKEN", "mcp-secret")
    settings = load_settings(tmp_path)
    assert settings.api_auth_token.get_secret_value() == "fallback-token"
    assert settings.mcp_servers["ticketing"].headers["Authorization"] == "Bearer mcp-secret"
