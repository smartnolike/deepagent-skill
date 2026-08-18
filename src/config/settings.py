"""Typed application settings loaded from an environment YAML file."""

# Pydantic SecretStr 防止密码和 Token 在 Settings 的字符串表示中泄露。

from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .agent_settings import AgentSettings
from .database_settings import DatabaseSettings
from .langfuse_settings import LangfuseSettings
from .mcp_server_settings import McpServerSettings
from .tool_settings import ToolSettings


class Settings(BaseSettings):
    """Validated runtime settings; secrets are intentionally redacted by Pydantic."""

    model_config = SettingsConfigDict(env_file=None, extra="forbid")

    agent_env: Literal["local", "dev", "prod"]
    agent: AgentSettings = AgentSettings()
    tools: ToolSettings = ToolSettings()
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    database: DatabaseSettings
    api_auth_token: SecretStr
    mcp_servers: dict[str, McpServerSettings] = Field(default_factory=dict)
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    log_include_stacktrace: bool = True
    allow_test_doubles: bool = False

    @field_validator("mcp_servers", mode="before")
    @classmethod
    def normalize_empty_mcp_servers(cls, value: object) -> object:
        """允许 YAML 的 ``mcp_servers:`` 空值表示没有启用 MCP。"""
        return {} if value is None else value

    @model_validator(mode="after")
    def validate_database_auth(self) -> "Settings":
        if self.agent_env == "local" and not self.database.password:
            raise ValueError("database.password is required for local")
        self.langfuse.validate_sources(self.agent_env)
        return self

    @property
    def async_sqlalchemy_url(self) -> str:
        """Return an asyncpg URL without exposing it through logs."""
        return self._postgres_url("postgresql+asyncpg")

    @property
    def psycopg_url(self) -> str:
        """Return a psycopg3 URL for the LangGraph checkpointer."""
        return self._postgres_url("postgresql")

    def _postgres_url(self, scheme: str) -> str:
        password = self.database.password
        credentials = quote_plus(self.database.user)
        if password:
            credentials = f"{credentials}:{quote_plus(password)}"
        return (
            f"{scheme}://{credentials}@{self.database.host}:{self.database.port}/"
            f"{quote_plus(self.database.name)}"
        )
