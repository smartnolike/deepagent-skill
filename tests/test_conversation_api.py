"""Conversation API integration tests."""

# 覆盖鉴权、会话隔离、分页、SSE 工单链路和长期记忆隔离。


def test_auth_and_conversation_lifecycle(client) -> None:
    assert client.post("/api/conversations", json={"staff_id": "staff-a"}).status_code == 401
    headers = {"Authorization": "Bearer test-token", "X-Request-ID": "request-1"}
    created = client.post("/api/conversations", headers=headers, json={"staff_id": "staff-a"})
    assert created.status_code == 200
    assert created.headers["X-Request-ID"] == "request-1"
    conversation_id = created.json()["id"]
    denied = client.get(f"/api/conversations/{conversation_id}?staff_id=staff-b", headers=headers)
    assert denied.status_code == 404
    history = client.get(f"/api/conversations/{conversation_id}/messages?staff_id=staff-a", headers=headers)
    assert history.json() == []


def test_bucket_ticket_stream(client) -> None:
    headers = {"Authorization": "Bearer test-token"}
    conversation_id = client.post("/api/conversations", headers=headers, json={"staff_id": "staff-a"}).json()["id"]
    first = client.post(
        f"/api/conversations/{conversation_id}/messages", headers=headers,
        json={"staff_id": "staff-a", "content": "我要申请一个 bucket"},
    )
    assert "ticketing__get_resource_schema" in first.text
    second = client.post(
        f"/api/conversations/{conversation_id}/messages", headers=headers,
        json={"staff_id": "staff-a", "content": "us-east1，用 STANDARD"},
    )
    assert "REQ-10001" in second.text
    history = client.get(f"/api/conversations/{conversation_id}/messages?staff_id=staff-a", headers=headers)
    assert len(history.json()) == 4


def test_list_conversations_is_paginated(client) -> None:
    headers = {"Authorization": "Bearer test-token"}
    for title in ("one", "two", "three"):
        client.post("/api/conversations", headers=headers, json={"staff_id": "staff-a", "title": title})
    page = client.get("/api/conversations?staff_id=staff-a&page=2&page_size=2", headers=headers)
    assert page.status_code == 200
    assert page.json()["page"] == 2
    assert page.json()["page_size"] == 2
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 1


def test_explicit_memories_are_staff_isolated(client) -> None:
    headers = {"Authorization": "Bearer test-token"}
    created = client.put(
        "/api/memories/default-region",
        headers=headers,
        json={"staff_id": "staff-a", "key": "default-region", "value": {"region": "us-east1"}},
    )
    assert created.status_code == 200
    assert client.get("/api/memories?staff_id=staff-b", headers=headers).json() == []
    assert client.get("/api/memories?staff_id=staff-a", headers=headers).json() == [
        {"key": "default-region", "value": {"region": "us-east1"}}
    ]
    assert client.delete("/api/memories/default-region?staff_id=staff-a", headers=headers).status_code == 204
