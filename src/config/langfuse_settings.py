"""Langfuse observability configuration."""

# local 使用直接 Key；dev/prod 仅保存 Google Secret Manager 的 Secret Version 引用。

from typing import Literal

from pydantic import BaseModel, SecretStr, field_validator


class LangfuseSettings(BaseModel):
    """Configure optional Langfuse tracing without exposing credentials in YAML logs."""

    enabled: bool = False
    public_key: SecretStr | None = None
    secret_key: SecretStr | None = None
    public_key_secret: str | None = None
    secret_key_secret: str | None = None
    base_url: str = "https://cloud.langfuse.com"
    release: str | None = None

    @field_validator("public_key", "secret_key", mode="after")
    @classmethod
    def normalize_empty_key(cls, value: SecretStr | None) -> SecretStr | None:
        """将 YAML 环境变量展开得到的空 Key 统一视为未配置。"""
        if value is None or not value.get_secret_value().strip():
            return None
        return value

    @field_validator("public_key_secret", "secret_key_secret", "release", mode="after")
    @classmethod
    def normalize_empty_string(cls, value: str | None) -> str | None:
        """将空字符串变为 None，便于 disabled 配置保留空环境变量默认值。"""
        if value is None or not value.strip():
            return None
        return value

    def validate_sources(self, agent_env: Literal["local", "dev", "prod"]) -> None:
        """按运行环境强制 Langfuse Key 的唯一来源。"""
        if not self.enabled:
            return
        direct_keys_configured = self.public_key is not None and self.secret_key is not None
        secret_versions_configured = (
            self.public_key_secret is not None and self.secret_key_secret is not None
        )
        if agent_env == "local":
            if not direct_keys_configured or self.public_key_secret or self.secret_key_secret:
                raise ValueError("local Langfuse requires public_key and secret_key only")
            return
        if not secret_versions_configured or self.public_key is not None or self.secret_key is not None:
            raise ValueError("dev/prod Langfuse requires public_key_secret and secret_key_secret only")
