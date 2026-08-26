"""Settings validation tests."""

# 覆盖 YAML 环境变量展开及不同环境下数据库认证规则。

import pytest
from pydantic import ValidationError

from config.load_settings import load_settings
from config.settings import Settings


def test_local_requires_password() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {"agent_env": "local", "allow_test_doubles": True, "database": {"host": "x", "name": "x", "user": "x"}, "api_auth_token": "x", "mcp_servers": {}}
        )


def test_dev_allows_no_password() -> None:
    settings = Settings.model_validate(
        {"agent_env": "dev", "allow_test_doubles": True, "database": {"host": "x", "name": "x", "user": "x"}, "api_auth_token": "x", "mcp_servers": {}}
    )
    assert settings.database.password is None


def test_local_shell_rejects_execution_without_human_confirmation() -> None:
    with pytest.raises(ValidationError, match="local_shell requires execute_requires_confirmation"):
        Settings.model_validate(
            {
                "agent_env": "local",
                "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
                "api_auth_token": "x",
                "mcp_servers": {},
                "sandbox": {
                    "provider": "local_shell",
                    "allow_agent_shell": True,
                    "execute_requires_confirmation": False,
                },
            }
        )


def test_gke_agent_requires_connection_settings() -> None:
    with pytest.raises(ValidationError, match="sandbox.gke is required"):
        Settings.model_validate(
            {
                "agent_env": "dev",
                "database": {"host": "x", "name": "x", "user": "x"},
                "api_auth_token": "x",
                "mcp_servers": {},
                "sandbox": {"provider": "gke_agent"},
            }
        )


def test_gke_agent_requires_a_template() -> None:
    with pytest.raises(ValidationError, match="template_name"):
        Settings.model_validate(
            {
                "agent_env": "dev",
                "database": {"host": "x", "name": "x", "user": "x"},
                "api_auth_token": "x",
                "mcp_servers": {},
                "sandbox": {
                    "provider": "gke_agent",
                    "gke": {
                        "namespace": "agent-sandbox",
                        "router_url": "http://sandbox-router:8080",
                    },
                },
            }
        )


def test_gke_tunnel_does_not_require_a_router_url() -> None:
    settings = Settings.model_validate(
        {
            "agent_env": "local",
            "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
            "api_auth_token": "x",
            "mcp_servers": {},
            "sandbox": {
                "provider": "gke_agent",
                "gke": {
                    "namespace": "agent-sandbox",
                    "template_name": "deepagent-runtime",
                    "connection_mode": "tunnel",
                },
            },
        }
    )

    assert settings.sandbox.gke is not None
    assert settings.sandbox.gke.router_url is None


def test_empty_mcp_servers_yaml_value_is_treated_as_no_enabled_servers() -> None:
    settings = Settings.model_validate(
        {
            "agent_env": "local",
            "allow_test_doubles": True,
            "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
            "api_auth_token": "x",
            "mcp_servers": None,
        }
    )
    assert settings.mcp_servers == {}


def test_settings_allow_missing_model_before_agent_factory_initialization() -> None:
    settings = Settings.model_validate(
        {"agent_env": "local", "database": {"host": "x", "name": "x", "user": "x", "password": "x"}, "api_auth_token": "x", "mcp_servers": {}}
    )
    assert settings.agent.model is None


def test_yaml_expands_environment_references(tmp_path, monkeypatch) -> None:
    (tmp_path / "local.yaml").write_text(
        """agent_env: local
allow_test_doubles: true
database: {host: localhost, name: deepagent, user: postgres, password: "${DB_PASSWORD}"}
api_auth_token: "${API_TOKEN:-fallback-token}"
mcp_servers:
  danaan:
    transport: http
    url: https://mcp.example.internal/api
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
    assert settings.mcp_servers["danaan"].headers["Authorization"] == "Bearer mcp-secret"


def test_local_langfuse_accepts_direct_environment_keys() -> None:
    settings = Settings.model_validate(
        {
            "agent_env": "local",
            "allow_test_doubles": True,
            "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
            "api_auth_token": "x",
            "mcp_servers": {},
            "langfuse": {"enabled": True, "public_key": "pk-local", "secret_key": "sk-local"},
        }
    )

    assert settings.langfuse.enabled is True
    assert settings.langfuse.public_key is not None


def test_dev_langfuse_requires_secret_manager_versions() -> None:
    with pytest.raises(ValidationError, match="dev/prod Langfuse requires"):
        Settings.model_validate(
            {
                "agent_env": "dev",
                "allow_test_doubles": True,
                "database": {"host": "x", "name": "x", "user": "x"},
                "api_auth_token": "x",
                "mcp_servers": {},
                "langfuse": {"enabled": True, "public_key": "pk-dev", "secret_key": "sk-dev"},
            }
        )


def test_prod_langfuse_accepts_secret_manager_versions() -> None:
    settings = Settings.model_validate(
        {
            "agent_env": "prod",
            "allow_test_doubles": True,
            "database": {"host": "x", "name": "x", "user": "x"},
            "api_auth_token": "x",
            "mcp_servers": {},
            "langfuse": {
                "enabled": True,
                "public_key_secret": "projects/example/secrets/langfuse-public/versions/1",
                "secret_key_secret": "projects/example/secrets/langfuse-secret/versions/1",
            },
        }
    )

    assert settings.langfuse.secret_key_secret is not None


def test_dynamic_token_auth_requires_model_base_url() -> None:
    with pytest.raises(ValidationError, match="agent.base_url"):
        Settings.model_validate(
            {
                "agent_env": "local",
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
            "agent_env": "dev",
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
                "agent_env": "dev",
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
                "agent_env": "local",
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
                "agent_env": "local",
                "allow_test_doubles": True,
                "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
                "api_auth_token": "x",
                "mcp_servers": {},
                "agent": {"provider": "openai_compatible", "api_key": "test-key"},
            }
        )
