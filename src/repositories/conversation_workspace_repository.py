"""Persistence for shared-Sandbox directory retention."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.agent.conversation_workspace import ConversationWorkspace


class ConversationWorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def touch(self, conversation_id: uuid.UUID, staff_id: str) -> None:
        workspace = await self._session.get(ConversationWorkspace, conversation_id)
        if workspace is None:
            self._session.add(ConversationWorkspace(conversation_id=conversation_id, staff_id=staff_id))
        else:
            workspace.staff_id = staff_id
        await self._session.commit()

    async def expired(self, cutoff: datetime) -> list[ConversationWorkspace]:
        result = await self._session.scalars(
            select(ConversationWorkspace).where(ConversationWorkspace.last_activity_at < cutoff)
        )
        return list(result)

    async def delete(self, workspace: ConversationWorkspace) -> None:
        await self._session.delete(workspace)
        await self._session.commit()
