"""Typed application settings loaded from an environment YAML file."""

# Pydantic SecretStr 防止密码和 Token 在 Settings 的字符串表示中泄露。

from typing import Literal
from urllib.parse import quote_plus

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .agent_settings import AgentSettings
from .database_settings import DatabaseSettings
from .mcp_server_settings import McpServerSettings
from .tool_settings import ToolSettings


class Settings(BaseSettings):
    """Validated runtime settings; secrets are intentionally redacted by Pydantic."""

    model_config = SettingsConfigDict(env_file=None, extra="forbid")

    app_env: Literal["local", "dev", "prod"]
    agent: AgentSettings = AgentSettings()
    tools: ToolSettings = ToolSettings()
    database: DatabaseSettings
    api_auth_token: SecretStr
    mcp_servers: dict[str, McpServerSettings]
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    @model_validator(mode="after")
    def validate_database_auth(self) -> "Settings":
        if self.app_env == "local" and not self.database.password:
            raise ValueError("database.password is required for local")
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
