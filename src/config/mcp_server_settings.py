"""MCP server YAML configuration model."""

# 每个 MCP Server 独立声明 transport、headers、重连策略和允许暴露的工具。

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class McpServerSettings(BaseModel):
    """Connection and tool allowlist for one MCP server."""

    transport: Literal["http", "stdio", "mock"]
    url: HttpUrl | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 15.0
    reconnect_initial_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 30.0
    tools: list[str] = Field(default_factory=list)
