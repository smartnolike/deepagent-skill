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
    context_argument_bindings: dict[str, dict[str, Literal["staff_id", "conversation_id"]]] = Field(
        default_factory=dict
    )
    fixed_arguments: dict[str, dict[str, str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tool_policies(self) -> "McpServerSettings":
        """Ensure Tool policies only target allowlisted Tools and never overlap by argument path."""
        configured_tools = set(self.tools)
        unknown = set(self.confirmation_required_tools) - configured_tools
        if unknown:
            raise ValueError(f"confirmation_required_tools are not allowlisted: {', '.join(sorted(unknown))}")
        policy_tools = set(self.context_argument_bindings) | set(self.fixed_arguments)
        unknown_policy_tools = policy_tools - configured_tools
        if unknown_policy_tools:
            raise ValueError(f"system argument policies are not allowlisted: {', '.join(sorted(unknown_policy_tools))}")
        for tool_name in policy_tools:
            overlapping_paths = set(self.context_argument_bindings.get(tool_name, {})) & set(
                self.fixed_arguments.get(tool_name, {})
            )
            if overlapping_paths:
                raise ValueError(
                    f"system argument paths overlap for {tool_name}: {', '.join(sorted(overlapping_paths))}"
                )
        return self
