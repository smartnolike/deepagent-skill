"""Danaan base-context long-term memory tests."""

# 验证业务记忆使用 LangGraph Store，并且不会保存资源模板等非稳定字段。

import pytest
from langgraph.store.memory import InMemoryStore

from core.errors import DomainError
from services.danaan_memory import DANAAN_BASE_CONTEXT_KEY, extract_danaan_base_context
from services.memory_service import MemoryService


@pytest.mark.asyncio
async def test_danaan_base_context_is_saved_and_loaded_by_exact_key() -> None:
    memory_service = MemoryService(InMemoryStore())
    context = extract_danaan_base_context(
        {
            "resourceOnboardRegion": "ASP",
            "applicationName": "payment-platform",
            "eimId": "EIM-100001",
            "envName": "dev",
            "useCaseShortName": "payments",
            "resourceContent": "must-not-be-saved",
        }
    )

    await memory_service.put("staff-a", DANAAN_BASE_CONTEXT_KEY, context)

    assert await memory_service.get("staff-a", DANAAN_BASE_CONTEXT_KEY) == {
        "resourceOnboardRegion": "ASP",
        "applicationName": "payment-platform",
        "eimId": "EIM-100001",
        "envName": "dev",
        "useCaseShortName": "payments",
    }
    assert await memory_service.get("staff-b", DANAAN_BASE_CONTEXT_KEY) is None


def test_danaan_base_context_rejects_missing_or_non_string_values() -> None:
    with pytest.raises(DomainError, match="envName must be a non-empty string"):
        extract_danaan_base_context(
            {
                "resourceOnboardRegion": "ASP",
                "applicationName": "payment-platform",
                "eimId": "EIM-100001",
                "envName": "",
                "useCaseShortName": "payments",
            }
        )
