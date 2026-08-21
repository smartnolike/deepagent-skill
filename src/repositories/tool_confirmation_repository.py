"""CRUD operations for durable Tool confirmation records."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.agent.tool_confirmation import ToolConfirmation


class ToolConfirmationRepository:
    """Persist user-facing approval state independently from Agent checkpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        conversation_id: uuid.UUID,
        agent_run_id: uuid.UUID,
        tool_name: str,
        description: str,
        display_arguments: dict[str, object],
    ) -> ToolConfirmation:
        """Create and commit a pending confirmation before it is sent by SSE."""
        confirmation = ToolConfirmation(
            conversation_id=conversation_id,
            agent_run_id=agent_run_id,
            tool_name=tool_name,
            description=description,
            display_arguments=display_arguments,
        )
        self._session.add(confirmation)
        await self._session.commit()
        await self._session.refresh(confirmation)
        return confirmation

    async def get(self, confirmation_id: uuid.UUID, conversation_id: uuid.UUID) -> ToolConfirmation | None:
        """Return one confirmation scoped to its conversation."""
        return await self._session.scalar(
            select(ToolConfirmation).where(
                ToolConfirmation.id == confirmation_id,
                ToolConfirmation.conversation_id == conversation_id,
            )
        )

    async def list(self, conversation_id: uuid.UUID, decision: str | None = None) -> list[ToolConfirmation]:
        """List confirmation records in creation order, optionally by decision."""
        statement = select(ToolConfirmation).where(ToolConfirmation.conversation_id == conversation_id)
        if decision is not None:
            statement = statement.where(ToolConfirmation.decision == decision)
        statement = statement.order_by(ToolConfirmation.created_at.asc())
        return list(await self._session.scalars(statement))

    async def decide(self, confirmation: ToolConfirmation, staff_id: str, action: str) -> ToolConfirmation:
        """Persist one irreversible approval or rejection decision."""
        confirmation.decision = action
        confirmation.decided_by_staff_id = staff_id
        confirmation.decided_at = datetime.now(timezone.utc)
        confirmation.execution_status = "running" if action == "approve" else "not_started"
        await self._session.commit()
        await self._session.refresh(confirmation)
        return confirmation

    async def mark_succeeded(self, confirmation: ToolConfirmation) -> None:
        """Record completion after an approved Tool call returns successfully."""
        confirmation.execution_status = "succeeded"
        await self._session.commit()

    async def mark_failed(self, confirmation: ToolConfirmation) -> None:
        """Record a failed approved Tool call without persisting exception details."""
        confirmation.execution_status = "failed"
        await self._session.commit()

    async def mark_cancelled(self, confirmation: ToolConfirmation) -> None:
        """Record an interrupted approved Tool call after the client stream disconnects."""
        confirmation.execution_status = "cancelled"
        await self._session.commit()
