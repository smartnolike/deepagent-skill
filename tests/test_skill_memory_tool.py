"""Skill-scoped long-term memory Tool tests."""

# 验证根 Agent 不预加载记忆后，Tool 仍会严格按 runtime staff_id 和 key 白名单读取。

import json

import pytest
from langchain.tools import ToolRuntime
from langgraph.store.memory import InMemoryStore

from services.danaan_memory import DANAAN_BASE_CONTEXT_KEY
from services.memory_service import MemoryService
from tools.skill_memory import create_get_skill_memory_tool


@pytest.mark.asyncio
async def test_skill_memory_tool_reads_only_current_staff_allowlisted_memory() -> None:
    """Tool 不接受外部 staff_id，且拒绝未授权的记忆 key。"""
    memory_service = MemoryService(InMemoryStore())
    await memory_service.put("staff-a", DANAAN_BASE_CONTEXT_KEY, {"applicationName": "payments"})
    tool = create_get_skill_memory_tool(memory_service)
    runtime = ToolRuntime(
        state={},
        context={
            "staff_id": "staff-a",
            "conversation_id": "conversation-a",
            "request_id": "request-a",
            "response_language": "en",
        },
        config={},
        stream_writer=lambda _: None,
        tool_call_id=None,
        store=None,
    )

    assert tool.coroutine is not None
    found = json.loads(await tool.coroutine(DANAAN_BASE_CONTEXT_KEY, runtime))
    denied = json.loads(await tool.coroutine("jira:default-project", runtime))

    assert found == {
        "found": True,
        "key": DANAAN_BASE_CONTEXT_KEY,
        "value": {"applicationName": "payments"},
    }
    assert denied["found"] is False
    assert denied["error"] == "memory key is not allowed"
