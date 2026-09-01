"""Activity records for directories inside the shared GKE Sandbox."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ConversationWorkspace(Base):
    __tablename__ = "ai_agent_conversation_workspaces"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_agent_conversation.id", ondelete="CASCADE"), primary_key=True
    )
    staff_id: Mapped[str] = mapped_column(String(255))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
