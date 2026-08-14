"""Conversation persistence model."""

# ai_agent_ 前缀区分本应用业务表与 LangGraph 自动维护的内部表。

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class Conversation(Base):
    """A staff-owned visible chat conversation."""

    __tablename__ = "ai_agent_conversation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staff_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
