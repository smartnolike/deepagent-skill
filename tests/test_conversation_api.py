"""Conversation API integration tests."""

# 覆盖鉴权、会话隔离、分页、SSE 工单链路和长期记忆隔离。


def test_auth_and_conversation_lifecycle(client) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.post("/agent/api/conversations", json={"staff_id": "staff-a"}).status_code == 401
    headers = {"Authorization": "Bearer test-token", "X-Request-ID": "request-1"}
    created = client.post("/agent/api/conversations", headers=headers, json={"staff_id": "staff-a"})
    assert created.status_code == 200
    assert created.headers["X-Request-ID"] == "request-1"
    conversation_id = created.json()["id"]
    renamed = client.patch(
        f"/agent/api/conversations/{conversation_id}",
        headers=headers,
        json={"staff_id": "staff-a", "title": "Cloud SQL 申请"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Cloud SQL 申请"
    assert client.patch(
        f"/agent/api/conversations/{conversation_id}",
        headers=headers,
        json={"staff_id": "staff-b", "title": "forbidden"},
    ).status_code == 404
    denied = client.get(f"/agent/api/conversations/{conversation_id}?staff_id=staff-b", headers=headers)
    assert denied.status_code == 404
    assert denied.json()["message"] == "Conversation not found"
    history = client.get(f"/agent/api/conversations/{conversation_id}/messages?staff_id=staff-a", headers=headers)
    assert history.json() == []


def test_message_stream_uses_test_agent_injected_at_application_boundary(client) -> None:
    headers = {"Authorization": "Bearer test-token"}
    conversation_id = client.post("/agent/api/conversations", headers=headers, json={"staff_id": "staff-a"}).json()["id"]
    response = client.post(
        f"/agent/api/conversations/{conversation_id}/messages",
        headers=headers,
        json={"staff_id": "staff-a", "content": "Please create a resource"},
    )
    assert "Test agent response." in response.text


def test_list_conversations_is_paginated(client) -> None:
    headers = {"Authorization": "Bearer test-token"}
    for title in ("one", "two", "three"):
        client.post("/agent/api/conversations", headers=headers, json={"staff_id": "staff-a", "title": title})
    page = client.get("/agent/api/conversations?staff_id=staff-a&page=2&page_size=2", headers=headers)
    assert page.status_code == 200
    assert page.json()["page"] == 2
    assert page.json()["page_size"] == 2
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 1


def test_explicit_memories_are_staff_isolated(client) -> None:
    headers = {"Authorization": "Bearer test-token"}
    created = client.put(
        "/agent/api/memories/default-region",
        headers=headers,
        json={"staff_id": "staff-a", "key": "default-region", "value": {"region": "us-east1"}},
    )
    assert created.status_code == 200
    assert client.get("/agent/api/memories?staff_id=staff-b", headers=headers).json() == []
    assert client.get("/agent/api/memories?staff_id=staff-a", headers=headers).json() == [
        {"key": "default-region", "value": {"region": "us-east1"}}
    ]
    assert client.delete("/agent/api/memories/default-region?staff_id=staff-a", headers=headers).status_code == 204


def test_agent_stream_failure_returns_safe_error_id(client, monkeypatch) -> None:
    """流已经开始后发生异常也必须返回可与后端日志关联的 error_id。"""
    headers = {"Authorization": "Bearer test-token"}
    conversation_id = client.post("/agent/api/conversations", headers=headers, json={"staff_id": "staff-a"}).json()["id"]

    async def failing_reply(*_):
        if False:
            yield "token", {"content": "unused"}
        raise RuntimeError("agent exploded")

    monkeypatch.setattr(client.app.state.agent_service, "reply", failing_reply)
    response = client.post(
        f"/agent/api/conversations/{conversation_id}/messages",
        headers=headers,
        json={"staff_id": "staff-a", "content": "hello"},
    )

    assert "event: error" in response.text
    assert '"code": "AGENT_ERROR"' in response.text
    assert '"error_id":' in response.text
