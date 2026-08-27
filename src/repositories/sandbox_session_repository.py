"""Persistence helpers for conversation workspace references."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.agent.sandbox_session import SandboxSession


class SandboxSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, conversation_id: uuid.UUID) -> SandboxSession | None:
        return await self._session.scalar(
            select(SandboxSession).where(
                SandboxSession.conversation_id == conversation_id,
                SandboxSession.status == "active",
            )
        )
