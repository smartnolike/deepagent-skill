"""Deterministic local fallback for the DeepAgent harness."""

# 此处保留确定性 fallback，真实环境由 harness_service 调用单一 DeepAgent。

import re
import uuid
from typing import AsyncIterator

from src.database.models.message import Message
from src.mcp.manager import McpClientManager


class MockHarnessService:
    """Run deterministic ticket behavior when no real model is configured."""

    def __init__(self, mcp_manager: McpClientManager) -> None:
        self._mcp_manager = mcp_manager

    async def reply(
        self, conversation_id: uuid.UUID, staff_id: str, content: str, history: list[Message]
    ) -> AsyncIterator[tuple[str, dict[str, str]]]:
        """Emit stable token/tool events for one staff-scoped Agent invocation."""
        _ = conversation_id, staff_id
        values = self._extract_values(history + [Message(role="user", content=content)])
        if not values["requested"]:
            yield "token", {"content": "我可以帮助你申请资源。请告诉我需要申请的资源类型。"}
            return
        yield "tool_start", {"name": "ticketing__get_resource_schema"}
        await self._mcp_manager.call_tool("ticketing__get_resource_schema", {"resource_type": "bucket"})
        yield "tool_end", {"name": "ticketing__get_resource_schema"}
        missing = [name for name in ("region", "storage_class") if not values[name]]
        if missing:
            label = "、".join("region（us-east1 或 us-west1）" if item == "region" else "storage_class（STANDARD 或 NEARLINE）" for item in missing)
            yield "token", {"content": f"申请 bucket 还需要提供：{label}。"}
            return
        parameters = {key: values[key] for key in ("region", "storage_class")}
        yield "tool_start", {"name": "ticketing__validate_ticket_params"}
        validation = await self._mcp_manager.call_tool(
            "ticketing__validate_ticket_params", {"resource_type": "bucket", "parameters": parameters}
        )
        yield "tool_end", {"name": "ticketing__validate_ticket_params"}
        if not validation["valid"]:
            yield "token", {"content": "参数还不完整，请补充缺失字段。"}
            return
        yield "tool_start", {"name": "ticketing__create_ticket"}
        ticket = await self._mcp_manager.call_tool(
            "ticketing__create_ticket", {"resource_type": "bucket", "parameters": parameters}
        )
        yield "tool_end", {"name": "ticketing__create_ticket"}
        yield "token", {"content": f"申请已创建，Ticket ID 为 {ticket['ticket_id']}。"}

    def _extract_values(self, messages: list[Message]) -> dict[str, str | bool | None]:
        text = " ".join(message.content.lower() for message in messages if message.role == "user")
        region = next((item for item in ("us-east1", "us-west1") if item in text), None)
        storage = next((item for item in ("standard", "nearline") if item in text), None)
        return {
            "requested": bool(re.search(r"bucket|桶|申请", text)),
            "region": region,
            "storage_class": storage.upper() if storage else None,
        }
