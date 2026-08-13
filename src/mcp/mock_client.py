"""Deterministic local MCP implementation."""

# Mock MCP 仅用于本地和测试，保证没有外部依赖时也可验证完整工单链路。

from typing import Any


class MockMcpClient:
    """Fake ticketing MCP server used by local development and tests."""

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "get_resource_schema":
            return {
                "type": "object",
                "properties": {
                    "region": {"type": "string", "enum": ["us-east1", "us-west1"]},
                    "storage_class": {"type": "string", "enum": ["STANDARD", "NEARLINE"]},
                    "retention_days": {"type": "integer", "minimum": 1},
                },
                "required": ["region", "storage_class"],
            }
        if tool_name == "validate_ticket_params":
            parameters = arguments.get("parameters", {})
            missing = [field for field in ("region", "storage_class") if not parameters.get(field)]
            return {"valid": not missing, "missing": missing, "errors": []}
        if tool_name == "create_ticket":
            return {"ticket_id": "REQ-10001", "status": "created"}
        raise ValueError(f"Unsupported mock MCP tool: {tool_name}")

    async def close(self) -> None:
        """Match real client lifecycle."""
