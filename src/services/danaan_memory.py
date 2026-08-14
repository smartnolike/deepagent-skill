"""Validated Danaan base-context memory helpers."""

# 仅保留稳定的基础资料；资源模板和完整工单参数不得写入长期记忆。

from typing import Any

from src.core.errors import DomainError

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
