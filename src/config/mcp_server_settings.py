"""MCP server YAML configuration model."""

# 每个 MCP Server 独立声明 transport、headers、重连策略和允许暴露的工具。

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class McpServerSettings(BaseModel):
    """Connection and tool allowlist for one MCP server."""

    enabled: bool = True
    transport: Literal["http"] = "http"
    url: HttpUrl | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    root_ca_path: Path | None = None
    timeout_seconds: float = 15.0
    reconnect_initial_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 30.0
    tools: list[str] = Field(default_factory=list)
    confirmation_required_tools: list[str] = Field(default_factory=list)
    frontend_diagnostic_tools: list[str] = Field(default_factory=list)
    expose_frontend_diagnostic_results: bool = False
    context_argument_bindings: dict[str, dict[str, Literal["staff_id", "conversation_id"]]] = Field(
        default_factory=dict
    )
    fixed_arguments: dict[str, dict[str, str]] = Field(default_factory=dict)

    @field_validator("root_ca_path", mode="after")
    @classmethod
    def resolve_root_ca_path(cls, value: Path | None) -> Path | None:
        """Resolve a configured CA file independently of the process working directory."""
        if value is None or value.is_absolute():
            return value
        return (PROJECT_ROOT / value).resolve()

    @model_validator(mode="after")
    def validate_tool_policies(self) -> "McpServerSettings":
        """Ensure Tool policies only target allowlisted Tools and never overlap by argument path."""
        configured_tools = set(self.tools)
        unknown = set(self.confirmation_required_tools) - configured_tools
        if unknown:
            raise ValueError(f"confirmation_required_tools are not allowlisted: {', '.join(sorted(unknown))}")
        unknown_diagnostic_tools = set(self.frontend_diagnostic_tools) - configured_tools
        if unknown_diagnostic_tools:
            raise ValueError(f"frontend_diagnostic_tools are not allowlisted: {', '.join(sorted(unknown_diagnostic_tools))}")
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
