"""Startup-only Google Secret Manager resolution tests."""

# 验证解析结果仅注入 RuntimeSecrets，后续 Token 刷新无需再次访问 Secret Manager。

import pytest
from pydantic import SecretStr

from config.settings import Settings
from core import startup_secrets


class FakeGoogleSecretManager:
    """记录启动期 Secret 读取与关闭调用的测试替身。"""

    def __init__(self) -> None:
        self.accessed: list[str] = []
        self.closed = False

    async def access_secret(self, secret_version_name: str) -> SecretStr:
        self.accessed.append(secret_version_name)
        return SecretStr("resolved-password")

    async def close(self) -> None:
        self.closed = True


def _settings(token_auth: dict[str, str], langfuse: dict[str, object] | None = None) -> Settings:
    """构造最小内部模型配置。"""
    return Settings.model_validate(
        {
            "agent_env": "dev",
            "allow_test_doubles": True,
            "database": {"host": "x", "name": "x", "user": "x"},
            "api_auth_token": "x",
            "mcp_servers": {},
            "agent": {"base_url": "https://model.example/v1", "token_auth": token_auth},
            "langfuse": langfuse or {},
        }
    )


@pytest.mark.asyncio
async def test_startup_resolves_secret_manager_password_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Secret reference 在启动期读取一次并注入内存。"""
    manager = FakeGoogleSecretManager()
    monkeypatch.setattr(startup_secrets, "GoogleSecretManager", lambda: manager)
    secret_version = "projects/example/secrets/model-password/versions/3"

    runtime_secrets = await startup_secrets.resolve_runtime_secrets(
        _settings(
            {
                "translator_url": "https://translator.example/token",
                "service_account_name": "svc",
                "service_account_password_secret": secret_version,
            }
        )
    )

    assert runtime_secrets.require_translator_service_account_password().get_secret_value() == "resolved-password"
    assert manager.accessed == [secret_version]
    assert manager.closed is True


@pytest.mark.asyncio
async def test_startup_uses_direct_local_password_without_secret_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """直接密码来源不创建或调用 Google Secret Manager。"""
    monkeypatch.setattr(startup_secrets, "GoogleSecretManager", lambda: pytest.fail("must not create manager"))

    runtime_secrets = await startup_secrets.resolve_runtime_secrets(
        _settings(
            {
                "translator_url": "https://translator.example/token",
                "service_account_name": "svc",
                "service_account_password": "local-password",
            }
        )
    )

    assert runtime_secrets.require_translator_service_account_password().get_secret_value() == "local-password"


@pytest.mark.asyncio
async def test_startup_resolves_langfuse_keys_from_secret_manager_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """dev/prod Langfuse Key 只在启动期读取并保留在 RuntimeSecrets。"""
    manager = FakeGoogleSecretManager()
    monkeypatch.setattr(startup_secrets, "GoogleSecretManager", lambda: manager)
    public_version = "projects/example/secrets/langfuse-public/versions/1"
    secret_version = "projects/example/secrets/langfuse-secret/versions/1"

    runtime_secrets = await startup_secrets.resolve_runtime_secrets(
        _settings(
            {
                "translator_url": "https://translator.example/token",
                "service_account_name": "svc",
                "service_account_password": "local-password",
            },
            {
                "enabled": True,
                "public_key_secret": public_version,
                "secret_key_secret": secret_version,
            },
        )
    )

    assert runtime_secrets.require_langfuse_public_key().get_secret_value() == "resolved-password"
    assert runtime_secrets.require_langfuse_secret_key().get_secret_value() == "resolved-password"
    assert manager.accessed == [public_version, secret_version]
    assert manager.closed is True
