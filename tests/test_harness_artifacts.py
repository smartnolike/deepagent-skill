import uuid

from agent.harness_service import DeepAgentHarnessService, _artifact_payload


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
