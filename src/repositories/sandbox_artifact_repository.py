"""Persistence helpers for temporary workspace artifacts."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.agent.sandbox_artifact import SandboxArtifact


class SandboxArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, artifact: SandboxArtifact) -> SandboxArtifact:
        self._session.add(artifact)
        await self._session.commit()
        await self._session.refresh(artifact)
        return artifact

    async def get(self, artifact_id: uuid.UUID, conversation_id: uuid.UUID) -> SandboxArtifact | None:
        return await self._session.scalar(
            select(SandboxArtifact).where(
                SandboxArtifact.id == artifact_id, SandboxArtifact.conversation_id == conversation_id
            )
        )

    async def list(self, conversation_id: uuid.UUID) -> list[SandboxArtifact]:
        result = await self._session.scalars(
            select(SandboxArtifact)
            .where(SandboxArtifact.conversation_id == conversation_id)
            .order_by(SandboxArtifact.created_at.asc())
        )
        return list(result)

    async def attach_to_assistant_message(self, agent_run_id: uuid.UUID, assistant_message_id: uuid.UUID) -> None:
        """Bind every Artifact published by one completed run to its visible reply."""
        await self._session.execute(
            update(SandboxArtifact)
            .where(
                SandboxArtifact.agent_run_id == agent_run_id,
                SandboxArtifact.assistant_message_id.is_(None),
            )
            .values(assistant_message_id=assistant_message_id)
        )
        await self._session.commit()
