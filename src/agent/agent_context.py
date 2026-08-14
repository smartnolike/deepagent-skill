"""Immutable runtime context supplied to every DeepAgent run."""

# 运行上下文包含员工、会话和记忆，不从静态 API Token 反推用户身份。

from typing import TypedDict

from src.common.language import ResponseLanguage


class AgentContext(TypedDict):
    """Identity and correlation values visible to the harness runtime."""

    staff_id: str
    conversation_id: str
    request_id: str
    response_language: ResponseLanguage
    memories: list[dict[str, object]]
    danaan_base_context: dict[str, str] | None
