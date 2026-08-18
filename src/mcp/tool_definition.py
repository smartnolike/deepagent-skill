"""Normalized MCP Tool metadata discovered from a server."""

# MCP Server 是 Tool 参数 schema 的唯一权威来源；本对象只保存其声明，不修改字段结构。

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class McpToolDefinition:
    """One allowlisted MCP Tool and its server-provided input schema."""

    name: str
    description: str
    input_schema: dict[str, Any]
