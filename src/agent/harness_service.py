"""Single-root DeepAgent harness invocation and SSE event adaptation."""
import json
# 将 DeepAgents 内部事件转换为稳定 SSE 事件，避免 API 暴露框架实现细节。

import uuid
import logging
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage
from langgraph.types import Command

from src.common.language import ResponseLanguage
from src.agent.mock_service import MockHarnessService
from src.database.models.agent.message import Message
from src.observability.langfuse_observability import LangfuseObservability

logger = logging.getLogger(__name__)


class DeepAgentHarnessService:
    """Use one configured Agent, with a deterministic local fallback."""

    def __init__(
        self,
        graph: Any | None,
        fallback: MockHarnessService,
        observability: LangfuseObservability | None = None,
    ) -> None:
        self._graph = graph
        self._fallback = fallback
        self._observability = observability

    async def reply(
        self,
        conversation_id: uuid.UUID,
        staff_id: str,
        agent_run_id: uuid.UUID,
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
        config = self._graph_config(conversation_id, staff_id, agent_run_id)
        logger.info("agent_invocation mode=deepagent conversation_id=%s staff_id=%s", conversation_id, staff_id)
        context = {
            "staff_id": staff_id,
            "conversation_id": str(conversation_id),
            "request_id": "-",
            "response_language": response_language,
        }
        async for event in self._stream_graph(
            {"messages": [("user", content)]},
            config,
            context,
        ):
            yield event

    async def resume(
        self,
        conversation_id: uuid.UUID,
        staff_id: str,
        agent_run_id: uuid.UUID,
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
        config = self._graph_config(conversation_id, staff_id, agent_run_id)
        context = {
            "staff_id": staff_id,
            "conversation_id": str(conversation_id),
            "request_id": "-",
            "response_language": response_language,
        }
        decision: dict[str, object] = {"type": action}
        if action == "respond":
            decision["message"] = json.dumps(response or {}, ensure_ascii=False)
        async for event in self._stream_graph(Command(resume={"decisions": [decision]}), config, context):
            yield event

    def _graph_config(self, conversation_id: uuid.UUID, staff_id: str, agent_run_id: uuid.UUID) -> dict[str, object]:
        """Build one LangGraph config with optional per-run Langfuse callback metadata."""
        config: dict[str, object] = {"configurable": {"thread_id": str(conversation_id)}}
        if self._observability is not None:
            config["callbacks"] = [self._observability.create_callback()]
            config["metadata"] = {
                "langfuse_session_id": str(conversation_id),
                "langfuse_user_id": staff_id,
                "conversation_id": str(conversation_id),
                "agent_run_id": str(agent_run_id),
            }
        return config

    async def _stream_graph(self, input_value: object, config: dict, context: dict) -> AsyncIterator[tuple[str, dict[str, str]]]:
        """将普通消息和 LangGraph HITL interrupt 统一转换为 API SSE 事件。"""
        active_tool_names: list[str] = []
        async for mode, value in self._graph.astream(input_value, config=config, context=context, stream_mode=["messages", "updates"]):
            if mode == "messages":
                message, metadata = value
                if not isinstance(message, AIMessage):
                    continue
                for tool_call in message.tool_calls:
                    tool_name = tool_call["name"]
                    active_tool_names.append(tool_name)
                    logger.info("agent_tool_requested tool_name=%s", tool_name)
                    if tool_name != "get_skill_memory":
                        yield "tool_start", {"name": tool_name}
                text = message.text if isinstance(message.text, str) else ""
                if text:
                    yield "token", {"content": text}
                if metadata.get("langgraph_node") == "tools":
                    for tool_name in active_tool_names:
                        if tool_name != "get_skill_memory":
                            yield "tool_end", {"name": tool_name}
                    active_tool_names.clear()
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
