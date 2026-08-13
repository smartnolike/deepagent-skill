"""Single-root DeepAgent harness invocation and SSE event adaptation."""

# 将 DeepAgents 内部事件转换为稳定 SSE 事件，避免 API 暴露框架实现细节。

import uuid
import json
import logging
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage

from src.agent.service import MockHarnessService
from src.database.models.message import Message
from src.services.memory_service import MemoryService

logger = logging.getLogger(__name__)


class DeepAgentHarnessService:
    """Use one configured DeepAgent, with a deterministic local fallback."""

    def __init__(self, graph: Any | None, fallback: MockHarnessService, memory_service: MemoryService) -> None:
        self._graph = graph
        self._fallback = fallback
        self._memory_service = memory_service

    async def reply(
        self, conversation_id: uuid.UUID, staff_id: str, content: str, history: list[Message]
    ) -> AsyncIterator[tuple[str, dict[str, str]]]:
        """Run the root agent under one thread ID and staff-scoped context."""
        if self._graph is None:
            logger.info("agent_invocation mode=mock conversation_id=%s", conversation_id)
            async for event in self._fallback.reply(conversation_id, staff_id, content, history):
                yield event
            return
        config = {"configurable": {"thread_id": str(conversation_id)}}
        logger.info("agent_invocation mode=deepagent conversation_id=%s staff_id=%s", conversation_id, staff_id)
        memories = await self._memory_service.list(staff_id)
        context = {
            "staff_id": staff_id,
            "conversation_id": str(conversation_id),
            "request_id": "-",
            "memories": memories,
        }
        async for message, metadata in self._graph.astream(
            {
                "messages": [
                    (
                        "system",
                        "Approved long-term memory for this staff member. Use it only when relevant; "
                        f"do not claim it was stated in this turn: {json.dumps(memories, ensure_ascii=False)}",
                    ),
                    ("user", content),
                ]
            },
            config=config,
            context=context,
            stream_mode="messages",
        ):
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
