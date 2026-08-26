import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models.agent.script_artifact import ScriptArtifact


class ScriptArtifactRepository:
    def __init__(self, session: AsyncSession) -> None: self._session = session
    async def create(self, artifact: ScriptArtifact) -> ScriptArtifact:
        self._session.add(artifact); await self._session.commit(); await self._session.refresh(artifact); return artifact
    async def get(self, artifact_id: uuid.UUID, conversation_id: uuid.UUID) -> ScriptArtifact | None:
        return await self._session.scalar(select(ScriptArtifact).where(ScriptArtifact.id == artifact_id, ScriptArtifact.conversation_id == conversation_id))
