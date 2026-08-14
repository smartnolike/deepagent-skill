"""Conversation title update request schema."""

# 标题更新独立定义请求模型，避免路由层直接依赖未校验的字典字段。

from pydantic import BaseModel, Field


class ConversationTitleRequest(BaseModel):
    """Payload for renaming or clearing a staff-owned conversation title."""

    staff_id: str = Field(min_length=1, max_length=255)
    title: str | None = Field(max_length=500)
