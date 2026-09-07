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
        ("tool_start", {"name": "lookup", "tool_call_id": "call-1"}),
        ("tool_end", {"name": "lookup", "tool_call_id": "call-1"}),
    ]


class _GraphWithDiagnosticToolResult:
    async def astream(self, *_args: object, **_kwargs: object):
        yield "messages", (AIMessage(content="", tool_calls=[{"name": "lookup", "args": {}, "id": "call-1"}]), {})
        yield "messages", (ToolMessage('{"status":"ok"}', name="lookup", tool_call_id="call-1"), {})


async def test_diagnostic_tool_emits_result_then_tool_end() -> None:
    harness = DeepAgentHarnessService(_GraphWithDiagnosticToolResult(), frontend_diagnostic_tools={"lookup": False})

    events = [event async for event in harness._stream_graph({}, {}, {})]

    assert [event for event, _payload in events] == ["tool_start", "tool_result", "tool_end"]
    assert events[1][1]["tool_call_id"] == "call-1"
    assert events[2][1]["tool_call_id"] == "call-1"


class _GraphWithRepeatedToolCalls:
    async def astream(self, *_args: object, **_kwargs: object):
        yield "messages", (
            AIMessage(content="", tool_calls=[
                {"name": "lookup", "args": {"query": "first"}, "id": "call-1"},
                {"name": "lookup", "args": {"query": "second"}, "id": "call-2"},
            ]),
            {},
        )
        yield "messages", (ToolMessage("second", name="lookup", tool_call_id="call-2"), {})
        yield "messages", (ToolMessage("first", name="lookup", tool_call_id="call-1"), {})


async def test_repeated_tool_calls_are_completed_by_tool_call_id() -> None:
    harness = DeepAgentHarnessService(_GraphWithRepeatedToolCalls())

    events = [event async for event in harness._stream_graph({}, {}, {})]

    assert events == [
        ("tool_start", {"name": "lookup", "tool_call_id": "call-1"}),
        ("tool_start", {"name": "lookup", "tool_call_id": "call-2"}),
        ("tool_end", {"name": "lookup", "tool_call_id": "call-2"}),
        ("tool_end", {"name": "lookup", "tool_call_id": "call-1"}),
    ]


class _GraphWithHiddenTool:
    async def astream(self, *_args: object, **_kwargs: object):
        yield "messages", (
            AIMessage(
                content="",
                tool_calls=[{"name": "get_skill_memory", "args": {}, "id": "call-1"}],
            ),
            {},
        )
        yield "messages", (ToolMessage("result", name="get_skill_memory", tool_call_id="call-1"), {})


async def test_hidden_tool_does_not_emit_lifecycle_events() -> None:
    harness = DeepAgentHarnessService(_GraphWithHiddenTool())

    assert [event async for event in harness._stream_graph({}, {}, {})] == []


class _GraphWithArtifactToolResult:
    async def astream(self, *_args: object, **_kwargs: object):
        yield "messages", (
            AIMessage(
                content="",
                tool_calls=[{"name": "publish_artifact", "args": {}, "id": "call-1"}],
            ),
            {},
        )
        yield "messages", (
            ToolMessage(
                '{"artifact_id":"artifact-1","filename":"report.xlsx","size_bytes":42}',
                name="publish_artifact",
                tool_call_id="call-1",
            ),
            {},
        )


async def test_artifact_tool_emits_artifact_then_tool_end() -> None:
    harness = DeepAgentHarnessService(_GraphWithArtifactToolResult())

    events = [event async for event in harness._stream_graph({}, {}, {})]

    assert events == [
        ("tool_start", {"name": "publish_artifact", "tool_call_id": "call-1"}),
        ("artifact_created", {"artifact_id": "artifact-1", "filename": "report.xlsx", "size_bytes": 42}),
        ("tool_end", {"name": "publish_artifact", "tool_call_id": "call-1"}),
    ]
