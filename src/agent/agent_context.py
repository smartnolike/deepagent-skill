"""Immutable runtime context supplied to every DeepAgent run."""

# 运行上下文只包含通用身份与关联信息；Skill 专属记忆必须按需通过受控 Tool 读取。

from typing import TypedDict

from src.common.language import ResponseLanguage


class AgentContext(TypedDict):
    """Identity and correlation values visible to the harness runtime."""

    staff_id: str
    conversation_id: str
    request_id: str
    response_language: ResponseLanguage
