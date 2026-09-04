"""Single-root DeepAgent harness invocation and SSE event adaptation."""

# 将 DeepAgents 内部事件转换为稳定 SSE 事件，避免 API 暴露框架实现细节。

import json
import logging
import uuid
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from common.language import ResponseLanguage
from database.models.agent.message import Message
from observability.langfuse_observability import LangfuseObservability

logger = logging.getLogger(__name__)


class DeepAgentHarnessService:
    """Use one configured DeepAgent and adapt its events to the API protocol."""

    def __init__(
        self,
        graph: Any,
        observability: LangfuseObservability | None = None,
        frontend_diagnostic_tools: dict[str, bool] | None = None,
        gke_workspace_service: Any | None = None,
    ) -> None:
        self._graph = graph
        self._observability = observability
        self._frontend_diagnostic_tools = frontend_diagnostic_tools or {}
        self.gke_workspace_service = gke_workspace_service

    async def reply(
        self,
        conversation_id: uuid.UUID,
        staff_id: str,
        agent_run_id: uuid.UUID,
        content: str,
        history: list[Message],
        response_language: ResponseLanguage,
    ) -> AsyncIterator[tuple[str, dict[str, object]]]:
        """Run the root agent under one thread ID and staff-scoped context."""
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
    ) -> AsyncIterator[tuple[str, dict[str, object]]]:
        """按当前会话 checkpoint 恢复一个已暂停的确认型 Tool 调用。"""
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
        # GKE's shared Sandbox maps this server-validated staff ID and thread
        # ID to /workspace/staff-workspaces/{staff_id}/{conversation_id}.
        config: dict[str, object] = {
            "configurable": {
                "thread_id": str(conversation_id),
                "staff_id": staff_id,
                "agent_run_id": str(agent_run_id),
            }
        }
        if self._observability is not None:
            config["callbacks"] = [self._observability.create_callback()]
            config["metadata"] = {
                "langfuse_session_id": str(conversation_id),
                "langfuse_user_id": staff_id,
                "conversation_id": str(conversation_id),
                "agent_run_id": str(agent_run_id),
            }
        return config


    async def _stream_graph(self, input_value: object, config: dict, context: dict) -> AsyncIterator[tuple[str, dict[str, object]]]:
        """将普通消息和 LangGraph HITL interrupt 统一转换为 API SSE 事件。"""
        active_tools: dict[str, dict[str, object]] = {}
        async for mode, value in self._graph.astream(input_value, config=config, context=context, stream_mode=["messages", "updates"]):
            if mode == "messages":
                message, metadata = value
                if isinstance(message, ToolMessage) and message.name == "publish_artifact":
                    artifact = _artifact_payload(message.content)
                    if artifact is not None:
                        yield "artifact_created", artifact
                    continue
                if isinstance(message, AIMessage):
                    for tool_call in message.tool_calls:
                        tool_name = tool_call["name"]
                        active_tools[tool_name] = _redact_tool_value(tool_call.get("args", {}))
                        logger.info("agent_tool_requested tool_name=%s", tool_name)
                        if tool_name != "get_skill_memory":
                            yield "tool_start", {"name": tool_name}
                    text = message.text if isinstance(message.text, str) else ""
                    if text:
                        yield "token", {"content": text}
                elif isinstance(message, ToolMessage) and message.name in self._frontend_diagnostic_tools:
                    yield "tool_result", _tool_result_payload(
                        message.name,
                        active_tools.get(message.name, {}),
                        message.content,
                        self._frontend_diagnostic_tools[message.name],
                    )
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
                            "arguments": pending.get("args", {}),
                        }


def _artifact_payload(content: object) -> dict[str, object] | None:
    """Extract the stable artifact fields from a publish_artifact Tool result."""
    value = content
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict) or not isinstance(value.get("artifact_id"), str):
        return None
    return {
        "artifact_id": value["artifact_id"],
        "filename": str(value.get("filename", "download")),
        "size_bytes": int(value.get("size_bytes", 0)),
    }


_SENSITIVE_KEY_PARTS = frozenset({"password", "secret", "token", "authorization", "credential", "api_key"})


def _redact_tool_value(value: object, key: str = "") -> object:
    """Return JSON-safe diagnostic data without credential-like values."""
    normalized_key = key.lower().replace("-", "_")
    if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact_tool_value(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact_tool_value(item, key) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _tool_result_payload(tool_name: str, arguments: object, content: object, expose_result: bool) -> dict[str, object]:
    """Build a frontend diagnostic record from a completed ToolMessage."""
    parsed_result: object = content
    source = "tool_message_text"
    if isinstance(content, str):
        try:
            parsed_result = json.loads(content)
            source = "tool_message_json"
        except json.JSONDecodeError:
            pass
    sanitized_result = _redact_tool_value(parsed_result)
    summary: dict[str, object] = {"result_type": type(parsed_result).__name__}
    if isinstance(parsed_result, dict):
        summary["top_level_keys"] = sorted(str(key) for key in parsed_result)
        data = parsed_result.get("data")
        summary["data"] = {
            "present": "data" in parsed_result,
            "is_non_empty_string": isinstance(data, str) and bool(data.strip()),
            "has_exactly_one_delimiter": isinstance(data, str) and data.count("@@") == 1,
        }
    payload: dict[str, object] = {
        "name": tool_name,
        "arguments": arguments,
        "source": source,
        "summary": summary,
    }
    if expose_result:
        payload["result"] = sanitized_result
    return payload
