from agent.harness_service import _artifact_payload


def test_artifact_tool_result_becomes_stable_sse_payload() -> None:
    assert _artifact_payload('{"artifact_id":"a-1","filename":"report.xlsx","size_bytes":42}') == {
        "artifact_id": "a-1",
        "filename": "report.xlsx",
        "size_bytes": 42,
    }


def test_non_artifact_tool_result_is_ignored() -> None:
    assert _artifact_payload("not json") is None
    assert _artifact_payload({"filename": "missing-id.xlsx"}) is None
