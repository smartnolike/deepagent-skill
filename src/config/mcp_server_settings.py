"""MCP server YAML configuration model."""

# 每个 MCP Server 独立声明 transport、headers、重连策略和允许暴露的工具。

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class McpServerSettings(BaseModel):
    """Connection and tool allowlist for one MCP server."""

    enabled: bool = True
    transport: Literal["http"] = "http"
    url: HttpUrl | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 15.0
    reconnect_initial_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 30.0
    tools: list[str] = Field(default_factory=list)
    confirmation_required_tools: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_confirmation_tools(self) -> "McpServerSettings":
        """避免配置不存在的 Tool，导致用户以为已受确认保护。"""
        unknown = set(self.confirmation_required_tools) - set(self.tools)
        if unknown:
            raise ValueError(f"confirmation_required_tools are not allowlisted: {', '.join(sorted(unknown))}")
        return self
