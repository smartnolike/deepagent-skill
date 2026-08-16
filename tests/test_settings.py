"""Settings validation tests."""

# 覆盖 YAML 环境变量展开及不同环境下数据库认证规则。

import pytest
from pydantic import ValidationError

from src.config.load_settings import load_settings
from src.config.settings import Settings


def test_local_requires_password() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {"app_env": "local", "allow_test_doubles": True, "database": {"host": "x", "name": "x", "user": "x"}, "api_auth_token": "x", "mcp_servers": {}}
        )


def test_dev_allows_no_password() -> None:
    settings = Settings.model_validate(
        {"app_env": "dev", "allow_test_doubles": True, "database": {"host": "x", "name": "x", "user": "x"}, "api_auth_token": "x", "mcp_servers": {}}
    )
    assert settings.database.password is None


def test_empty_mcp_servers_yaml_value_is_treated_as_no_enabled_servers() -> None:
    settings = Settings.model_validate(
        {
            "app_env": "local",
            "allow_test_doubles": True,
            "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
            "api_auth_token": "x",
            "mcp_servers": None,
        }
    )
    assert settings.mcp_servers == {}


def test_real_runtime_requires_agent_model() -> None:
    with pytest.raises(ValidationError, match="agent.model"):
        Settings.model_validate(
            {"app_env": "local", "database": {"host": "x", "name": "x", "user": "x", "password": "x"}, "api_auth_token": "x", "mcp_servers": {}}
        )


def test_yaml_expands_environment_references(tmp_path, monkeypatch) -> None:
    (tmp_path / "local.yaml").write_text(
        """app_env: local
allow_test_doubles: true
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
    monkeypatch.setenv("AGENT_ENV", "local")
    monkeypatch.setenv("DB_PASSWORD", "postgres")
    monkeypatch.setenv("MCP_TOKEN", "mcp-secret")
    settings = load_settings(tmp_path)
    assert settings.api_auth_token.get_secret_value() == "fallback-token"
    assert settings.mcp_servers["ticketing"].headers["Authorization"] == "Bearer mcp-secret"


def test_dynamic_token_auth_requires_model_base_url() -> None:
    with pytest.raises(ValidationError, match="agent.base_url"):
        Settings.model_validate(
            {
                "app_env": "local",
                "allow_test_doubles": True,
                "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
                "api_auth_token": "x",
                "mcp_servers": {},
                "agent": {
                    "token_auth": {
                        "translator_url": "https://translator.example/token",
                        "service_account_name": "svc",
                        "service_account_password": "secret",
                    }
                },
            }
        )


def test_dynamic_token_auth_accepts_secret_manager_reference() -> None:
    settings = Settings.model_validate(
        {
            "app_env": "dev",
            "allow_test_doubles": True,
            "database": {"host": "x", "name": "x", "user": "x"},
            "api_auth_token": "x",
            "mcp_servers": {},
            "agent": {
                "base_url": "https://model.example/v1",
                "token_auth": {
                    "translator_url": "https://translator.example/token",
                    "service_account_name": "svc",
                    "service_account_password_secret": "projects/example/secrets/model-password/versions/3",
                },
            },
        }
    )

    assert settings.agent.token_auth is not None
    assert settings.agent.token_auth.service_account_password is None


def test_dynamic_token_auth_rejects_multiple_password_sources() -> None:
    with pytest.raises(ValidationError, match="exactly one of service_account_password"):
        Settings.model_validate(
            {
                "app_env": "dev",
                "allow_test_doubles": True,
                "database": {"host": "x", "name": "x", "user": "x"},
                "api_auth_token": "x",
                "mcp_servers": {},
                "agent": {
                    "base_url": "https://model.example/v1",
                    "token_auth": {
                        "translator_url": "https://translator.example/token",
                        "service_account_name": "svc",
                        "service_account_password": "password",
                        "service_account_password_secret": "projects/example/secrets/model-password/versions/3",
                    },
                },
            }
        )


def test_openai_provider_rejects_internal_token_auth() -> None:
    with pytest.raises(ValidationError, match="agent.token_auth"):
        Settings.model_validate(
            {
                "app_env": "local",
                "allow_test_doubles": True,
                "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
                "api_auth_token": "x",
                "mcp_servers": {},
                "agent": {
                    "provider": "openai",
                    "token_auth": {
                        "translator_url": "https://translator.example/token",
                        "service_account_name": "svc",
                        "service_account_password": "secret",
                    },
                },
            }
        )


def test_openai_compatible_provider_requires_base_url() -> None:
    with pytest.raises(ValidationError, match="agent.base_url"):
        Settings.model_validate(
            {
                "app_env": "local",
                "allow_test_doubles": True,
                "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
                "api_auth_token": "x",
                "mcp_servers": {},
                "agent": {"provider": "openai_compatible", "api_key": "test-key"},
            }
        )
