"""Deterministic local fallback for the DeepAgent harness."""

# 此处保留确定性 fallback，真实环境由 harness_service 调用单一 DeepAgent。

import re
import uuid
from typing import AsyncIterator

from src.common.language import ResponseLanguage
from src.common.messages import user_message
from src.database.models.agent.message import Message
from src.mcp.manager import McpClientManager


class MockHarnessService:
    """Run deterministic ticket behavior when no real model is configured."""

    def __init__(self, mcp_manager: McpClientManager) -> None:
        self._mcp_manager = mcp_manager

    async def reply(
        self,
        conversation_id: uuid.UUID,
        staff_id: str,
        content: str,
        history: list[Message],
        response_language: ResponseLanguage,
    ) -> AsyncIterator[tuple[str, dict[str, str]]]:
        """Emit stable token/tool events for one staff-scoped Agent invocation."""
        _ = conversation_id, staff_id
        values = self._extract_values(history + [Message(role="user", content=content)])
        if not values["requested"]:
            yield "token", {"content": user_message("request_resource_type", response_language)}
            return
        yield "tool_start", {"name": "ticketing__get_resource_schema"}
        await self._mcp_manager.call_tool("ticketing__get_resource_schema", {"resource_type": "bucket"})
        yield "tool_end", {"name": "ticketing__get_resource_schema"}
        missing = [name for name in ("region", "storage_class") if not values[name]]
        if missing:
            labels = {
                "zh-CN": {"region": "region（us-east1 或 us-west1）", "storage_class": "storage_class（STANDARD 或 NEARLINE）"},
                "en": {"region": "region (us-east1 or us-west1)", "storage_class": "storage_class (STANDARD or NEARLINE)"},
            }
            separator = "、" if response_language == "zh-CN" else ", "
            yield "token", {
                "content": user_message(
                    "bucket_missing", response_language, fields=separator.join(labels[response_language][item] for item in missing)
                )
            }
            return
        parameters = {key: values[key] for key in ("region", "storage_class")}
        yield "tool_start", {"name": "ticketing__validate_ticket_params"}
        validation = await self._mcp_manager.call_tool(
            "ticketing__validate_ticket_params", {"resource_type": "bucket", "parameters": parameters}
        )
        yield "tool_end", {"name": "ticketing__validate_ticket_params"}
        if not validation["valid"]:
            yield "token", {"content": user_message("bucket_invalid", response_language)}
            return
        yield "tool_start", {"name": "ticketing__create_ticket"}
        if "create_ticket" in self._mcp_manager.server_settings["ticketing"].confirmation_required_tools:
            yield "confirmation_required", {
                "tool_name": "ticketing__create_ticket",
                "description": "Confirm ticket creation",
            }
            return
        ticket = await self._mcp_manager.call_tool(
            "ticketing__create_ticket", {"resource_type": "bucket", "parameters": parameters}
        )
        yield "tool_end", {"name": "ticketing__create_ticket"}
        yield "token", {"content": user_message("ticket_created", response_language, ticket_id=ticket["ticket_id"])}

    async def resume(
        self, action: str, history: list[Message], response_language: ResponseLanguage
    ) -> AsyncIterator[tuple[str, dict[str, str]]]:
        """在测试 fallback 中模拟用户确认或取消敏感 Tool。"""
        values = self._extract_values(history)
        if action == "reject":
            yield "token", {"content": "已取消本次工具执行。" if response_language == "zh-CN" else "This tool execution was cancelled."}
            return
        if action != "approve":
            raise ValueError("Mock harness supports only approve or reject for tool confirmation")
        parameters = {key: values[key] for key in ("region", "storage_class")}
        yield "tool_start", {"name": "ticketing__create_ticket"}
        ticket = await self._mcp_manager.call_tool(
            "ticketing__create_ticket", {"resource_type": "bucket", "parameters": parameters}
        )
        yield "tool_end", {"name": "ticketing__create_ticket"}
        yield "token", {"content": user_message("ticket_created", response_language, ticket_id=ticket["ticket_id"])}

    def _extract_values(self, messages: list[Message]) -> dict[str, str | bool | None]:
        text = " ".join(message.content.lower() for message in messages if message.role == "user")
        region = next((item for item in ("us-east1", "us-west1") if item in text), None)
        storage = next((item for item in ("standard", "nearline") if item in text), None)
        return {
            "requested": bool(re.search(r"bucket|桶|申请", text)),
            "region": region,
            "storage_class": storage.upper() if storage else None,
        }
