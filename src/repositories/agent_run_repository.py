"""Agent run lifecycle repository."""

# Agent run 记录调用结果；异常文本在上层脱敏后才会写入。

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.agent.agent_run import AgentRun


class AgentRunRepository:
    """Store the outcome of Agent calls without storing model state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, conversation_id: uuid.UUID, user_message_id: uuid.UUID) -> AgentRun:
        run = AgentRun(conversation_id=conversation_id, user_message_id=user_message_id, status="running")
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def complete(self, run: AgentRun) -> None:
        run.status = "completed"
        await self._session.commit()

    async def fail(self, run: AgentRun, error_message: str) -> None:
        run.status = "failed"
        run.error_message = error_message[:1000]
        await self._session.commit()

    async def cancel(self, run: AgentRun) -> None:
        """Mark a client-disconnected agent run without misclassifying it as a backend failure."""
        run.status = "cancelled"
        await self._session.commit()

    async def await_confirmation(self, run: AgentRun) -> None:
        """标记运行已由用户确认型 Tool 暂停。"""
        run.status = "awaiting_confirmation"
        await self._session.commit()

    async def get_awaiting_confirmation(self, conversation_id: uuid.UUID) -> AgentRun | None:
        """返回会话中唯一等待用户确认的运行。"""
        from sqlalchemy import select

        return await self._session.scalar(
            select(AgentRun)
            .where(AgentRun.conversation_id == conversation_id, AgentRun.status == "awaiting_confirmation")
            .order_by(AgentRun.created_at.desc())
        )
