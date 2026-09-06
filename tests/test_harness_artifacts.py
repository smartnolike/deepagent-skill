import uuid

from agent.harness_service import DeepAgentHarnessService, _artifact_payload
from langchain_core.messages import AIMessage, ToolMessage


def test_artifact_tool_result_becomes_stable_sse_payload() -> None:
    assert _artifact_payload('{"artifact_id":"a-1","filename":"report.xlsx","size_bytes":42}') == {
        "artifact_id": "a-1",
        "filename": "report.xlsx",
        "size_bytes": 42,
    }


def test_non_artifact_tool_result_is_ignored() -> None:
    assert _artifact_payload("not json") is None
    assert _artifact_payload({"filename": "missing-id.xlsx"}) is None


def test_graph_config_exposes_agent_run_to_publish_artifact() -> None:
    conversation_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()

    config = DeepAgentHarnessService(graph=None)._graph_config(conversation_id, "staff-a", agent_run_id)

    assert config["configurable"] == {
        "thread_id": str(conversation_id),
        "staff_id": "staff-a",
        "agent_run_id": str(agent_run_id),
    }


class _GraphWithToolResult:
    async def astream(self, *_args: object, **_kwargs: object):
        yield "messages", (AIMessage(content="", tool_calls=[{"name": "lookup", "args": {}, "id": "call-1"}]), {})
        yield "messages", (ToolMessage("result", name="lookup", tool_call_id="call-1"), {})


async def test_completed_tool_emits_tool_end_after_tool_start() -> None:
    harness = DeepAgentHarnessService(_GraphWithToolResult())

    events = [event async for event in harness._stream_graph({}, {}, {})]

    assert events == [
        ("tool_start", {"name": "lookup"}),
        ("tool_end", {"name": "lookup"}),
    ]


class _GraphWithDiagnosticToolResult:
    async def astream(self, *_args: object, **_kwargs: object):
        yield "messages", (AIMessage(content="", tool_calls=[{"name": "lookup", "args": {}, "id": "call-1"}]), {})
        yield "messages", (ToolMessage('{"status":"ok"}', name="lookup", tool_call_id="call-1"), {})


async def test_diagnostic_tool_emits_result_then_tool_end() -> None:
    harness = DeepAgentHarnessService(_GraphWithDiagnosticToolResult(), frontend_diagnostic_tools={"lookup": False})

    events = [event async for event in harness._stream_graph({}, {}, {})]

    assert [event for event, _payload in events] == ["tool_start", "tool_result", "tool_end"]
