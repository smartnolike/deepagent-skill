"""Single-root DeepAgent harness invocation and SSE event adaptation."""

# 将 DeepAgents 内部事件转换为稳定 SSE 事件，避免 API 暴露框架实现细节。

import uuid
import json
import logging
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage
from langgraph.types import Command

from src.common.language import ResponseLanguage
from src.agent.service import MockHarnessService
from src.database.models.agent.message import Message
from src.services.danaan_memory import DANAAN_BASE_CONTEXT_KEY
from src.services.memory_service import MemoryService

logger = logging.getLogger(__name__)


class DeepAgentHarnessService:
    """Use one configured DeepAgent, with a deterministic local fallback."""

    def __init__(self, graph: Any | None, fallback: MockHarnessService, memory_service: MemoryService) -> None:
        self._graph = graph
        self._fallback = fallback
        self._memory_service = memory_service

    async def reply(
        self,
        conversation_id: uuid.UUID,
        staff_id: str,
        content: str,
        history: list[Message],
        response_language: ResponseLanguage,
    ) -> AsyncIterator[tuple[str, dict[str, str]]]:
        """Run the root agent under one thread ID and staff-scoped context."""
        if self._graph is None:
            logger.info("agent_invocation mode=mock conversation_id=%s", conversation_id)
            async for event in self._fallback.reply(conversation_id, staff_id, content, history, response_language):
                yield event
            return
        config = {"configurable": {"thread_id": str(conversation_id)}}
        logger.info("agent_invocation mode=deepagent conversation_id=%s staff_id=%s", conversation_id, staff_id)
        memories = await self._memory_service.list(staff_id)
        danaan_base_context = await self._memory_service.get(staff_id, DANAAN_BASE_CONTEXT_KEY)
        context = {
            "staff_id": staff_id,
            "conversation_id": str(conversation_id),
            "request_id": "-",
            "response_language": response_language,
            "memories": memories,
            "danaan_base_context": danaan_base_context,
        }
        async for event in self._stream_graph(
            {
                "messages": [
                    (
                        "system",
                        "Approved long-term memory for this staff member. Use it only when relevant; "
                        f"do not claim it was stated in this turn: {json.dumps(memories, ensure_ascii=False)}\n\n"
                        "Danaan base context is a separate proposed default. It may be used only after the user "
                        "explicitly confirms it for this request: "
                        f"{json.dumps(danaan_base_context, ensure_ascii=False)}",
                    ),
                    ("user", content),
                ]
            },
            config,
            context,
        ):
            yield event

    async def resume(
        self,
        conversation_id: uuid.UUID,
        staff_id: str,
        action: str,
        history: list[Message],
        response_language: ResponseLanguage,
        response: dict[str, object] | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, str]]]:
        """按当前会话 checkpoint 恢复一个已暂停的确认型 Tool 调用。"""
        if self._graph is None:
            async for event in self._fallback.resume(action, history, response_language):
                yield event
            return
        config = {"configurable": {"thread_id": str(conversation_id)}}
        memories = await self._memory_service.list(staff_id)
        danaan_base_context = await self._memory_service.get(staff_id, DANAAN_BASE_CONTEXT_KEY)
        context = {
            "staff_id": staff_id,
            "conversation_id": str(conversation_id),
            "request_id": "-",
            "response_language": response_language,
            "memories": memories,
            "danaan_base_context": danaan_base_context,
        }
        decision: dict[str, object] = {"type": action}
        if action == "respond":
            decision["message"] = json.dumps(response or {}, ensure_ascii=False)
        async for event in self._stream_graph(Command(resume={"decisions": [decision]}), config, context):
            yield event

    async def _stream_graph(self, input_value: object, config: dict, context: dict) -> AsyncIterator[tuple[str, dict[str, str]]]:
        """将普通消息和 LangGraph HITL interrupt 统一转换为 API SSE 事件。"""
        async for mode, value in self._graph.astream(input_value, config=config, context=context, stream_mode=["messages", "updates"]):
            if mode == "messages":
                message, metadata = value
                if not isinstance(message, AIMessage):
                    continue
                for tool_call in message.tool_calls:
                    logger.info("agent_tool_requested tool_name=%s", tool_call["name"])
                    yield "tool_start", {"name": tool_call["name"]}
                text = message.text if isinstance(message.text, str) else ""
                if text:
                    yield "token", {"content": text}
                if metadata.get("langgraph_node") == "tools":
                    yield "tool_end", {"name": "mcp_tool"}
            elif mode == "updates" and isinstance(value, dict) and "__interrupt__" in value:
                for interrupt in value["__interrupt__"]:
                    request = getattr(interrupt, "value", interrupt)
                    actions = request.get("action_requests", []) if isinstance(request, dict) else []
                    for pending in actions:
                        tool_name = str(pending.get("name", "unknown"))
                        if tool_name == "request_user_form":
                            arguments = pending.get("args", {})
                            if not isinstance(arguments, dict):
                                arguments = {}
                            yield "form_required", {
                                "form_name": str(arguments.get("form_name", "resource_form")),
                                "title": str(arguments.get("title", "Resource information")),
                                "fields": arguments.get("fields", []),
                                "prefilled_values": arguments.get("prefilled_values", {}),
                            }
                            continue
                        yield "confirmation_required", {
                            "tool_name": tool_name,
                            "description": str(pending.get("description", "Confirm tool execution")),
                        }
