"""Persistent user decisions for confirmation-gated Agent tools."""

# LangGraph checkpoint 保存暂停点；本模型保存前端恢复和审计需要的业务审批记录。

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ToolConfirmation(Base):
    """One user confirmation request emitted by a single Agent run."""

    __tablename__ = "ai_agent_tool_confirmation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_agent_conversation.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_agent_agent_run.id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    display_arguments: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    decision: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    decided_by_staff_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_status: Mapped[str] = mapped_column(String(20), default="not_started")
    result_summary: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
