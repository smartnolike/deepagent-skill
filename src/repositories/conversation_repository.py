"""Conversation CRUD repository."""

# Repository 只执行 ORM CRUD，不包含 Agent、鉴权或 HTTP 规则。

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.conversation import Conversation


class ConversationRepository:
    """Persist and load staff-owned conversations only."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, staff_id: str, title: str | None = None) -> Conversation:
        conversation = Conversation(staff_id=staff_id, title=title)
        self._session.add(conversation)
        await self._session.commit()
        await self._session.refresh(conversation)
        return conversation

    async def get(self, conversation_id: uuid.UUID, staff_id: str) -> Conversation | None:
        return await self._session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.staff_id == staff_id
            )
        )

    async def list(self, staff_id: str, page: int, page_size: int) -> tuple[list[Conversation], int]:
        statement = select(Conversation).where(Conversation.staff_id == staff_id)
        total = await self._session.scalar(select(func.count()).select_from(statement.subquery()))
        result = await self._session.scalars(
            statement.order_by(Conversation.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        return list(result), total or 0

    async def delete(self, conversation: Conversation) -> None:
        await self._session.delete(conversation)
        await self._session.commit()
