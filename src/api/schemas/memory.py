"""Validated explicit-memory creation request."""

# 只接受字符串字段，降低复杂嵌套对象和潜在敏感数据被长期保存的风险。

from pydantic import BaseModel, Field


class MemoryRequest(BaseModel):
    """A caller-approved, string-only long-term memory value."""

    staff_id: str = Field(min_length=1, max_length=255)
    key: str = Field(min_length=1, max_length=255)
    value: dict[str, str]
