"""Validated Danaan base-context memory helpers."""

# 仅保留稳定的基础资料；资源模板和完整工单参数不得写入长期记忆。

from typing import Any

from core.errors import DomainError
from services.memory_service import MemoryService

DANAAN_BASE_CONTEXT_KEY = "danaan-cloud-resource:base-context"
DANAAN_BASE_CONTEXT_FIELDS = (
    "resourceOnboardRegion",
    "applicationName",
    "eimId",
    "envName",
    "useCaseShortName",
)


def extract_danaan_base_context(value: dict[str, Any]) -> dict[str, str]:
    """Validate and retain only the five Danaan fields eligible for long-term memory."""
    context: dict[str, str] = {}
    for field in DANAAN_BASE_CONTEXT_FIELDS:
        raw_value = value.get(field)
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise DomainError(
                "INVALID_DANAAN_BASE_CONTEXT",
                f"{field} must be a non-empty string",
                422,
            )
        context[field] = raw_value.strip()
    return context


async def save_danaan_base_context_from_form(
    memory_service: MemoryService, staff_id: str, response: dict[str, object] | None
) -> None:
    """Validate and persist Danaan's confirmed base-context form response only."""
    if response is None:
        raise DomainError("INVALID_DANAAN_BASE_CONTEXT", "Danaan base context response is required", 422)
    context = extract_danaan_base_context(response)
    await memory_service.put(staff_id, DANAAN_BASE_CONTEXT_KEY, context)
