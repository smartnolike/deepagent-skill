"""Message CRUD repository."""

# 可见消息与 LangGraph checkpoint 分离，前者只服务于聊天历史展示。

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.agent.message import Message


class MessageRepository:
    """Persist visible messages independent of Agent checkpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, conversation_id: uuid.UUID, role: str, content: str) -> Message:
        message = Message(conversation_id=conversation_id, role=role, content=content)
        self._session.add(message)
        await self._session.commit()
        await self._session.refresh(message)
        return message

    async def list(self, conversation_id: uuid.UUID) -> list[Message]:
        result = await self._session.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
        )
        return list(result)
