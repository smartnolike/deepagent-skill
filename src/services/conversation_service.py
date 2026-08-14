"""Conversation business operations."""

from __future__ import annotations

# 会话服务只协调持久化与 Agent 生命周期，Agent 推理期间不持有数据库事务。

import uuid
import logging
from collections.abc import AsyncIterator

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.harness_service import DeepAgentHarnessService
from src.common.language import ResponseLanguage
from src.common.language import resolve_response_language
from src.core.errors import DomainError
from src.repositories.agent_run_repository import AgentRunRepository
from src.repositories.conversation_repository import ConversationRepository
from src.repositories.message_repository import MessageRepository
from src.services.danaan_memory import save_danaan_base_context_from_form
from src.services.memory_service import MemoryService

logger = logging.getLogger(__name__)


class ConversationService:
    """Coordinate persisted chat history, Agent execution, and run lifecycle."""

    def __init__(
        self, session: AsyncSession, agent_service: DeepAgentHarnessService, memory_service: MemoryService
    ) -> None:
        self._conversations = ConversationRepository(session)
        self._messages = MessageRepository(session)
        self._runs = AgentRunRepository(session)
        self._agent_service = agent_service
        self._memory_service = memory_service

    async def create(self, staff_id: str, title: str | None) -> dict[str, str | None]:
        conversation = await self._conversations.create(staff_id, title)
        logger.info("conversation_created conversation_id=%s staff_id=%s", conversation.id, staff_id)
        return self._conversation_payload(conversation.id, conversation.title, conversation.created_at)

    async def list(self, staff_id: str, page: int, page_size: int) -> dict[str, int | list[dict[str, str | None]]]:
        conversations, total = await self._conversations.list(staff_id, page, page_size)
        return {
            "items": [self._conversation_payload(item.id, item.title, item.created_at) for item in conversations],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    async def get(self, conversation_id: uuid.UUID, staff_id: str, response_language: ResponseLanguage) -> dict[str, str | None]:
        conversation = await self._require_conversation(conversation_id, staff_id, response_language)
        return self._conversation_payload(conversation.id, conversation.title, conversation.created_at)

    async def update_title(
        self,
        conversation_id: uuid.UUID,
        staff_id: str,
        title: str | None,
        response_language: ResponseLanguage,
    ) -> dict[str, str | None]:
        """Rename or clear a staff-owned conversation title."""
        conversation = await self._require_conversation(conversation_id, staff_id, response_language)
        updated = await self._conversations.update_title(conversation, title)
        logger.info("conversation_title_updated conversation_id=%s staff_id=%s", conversation_id, staff_id)
        return self._conversation_payload(updated.id, updated.title, updated.created_at)

    async def delete(self, conversation_id: uuid.UUID, staff_id: str, response_language: ResponseLanguage) -> None:
        conversation = await self._require_conversation(conversation_id, staff_id, response_language)
        await self._conversations.delete(conversation)
        logger.info("conversation_deleted conversation_id=%s staff_id=%s", conversation_id, staff_id)

    async def messages(self, conversation_id: uuid.UUID, staff_id: str, response_language: ResponseLanguage) -> list[dict[str, str]]:
        await self._require_conversation(conversation_id, staff_id, response_language)
        messages = await self._messages.list(conversation_id)
        return [
            {"id": str(item.id), "role": item.role, "content": item.content, "created_at": item.created_at.isoformat()}
            for item in messages
        ]

    async def send(
        self, conversation_id: uuid.UUID, staff_id: str, content: str, response_language: ResponseLanguage
    ) -> AsyncIterator[tuple[str, dict[str, str]]]:
        await self._require_conversation(conversation_id, staff_id, response_language)
        user_message = await self._messages.create(conversation_id, "user", content)
        run = await self._runs.create(conversation_id, user_message.id)
        logger.info("agent_run_started agent_run_id=%s conversation_id=%s staff_id=%s", run.id, conversation_id, staff_id)
        history = await self._messages.list(conversation_id)
        last_user_content = next((message.content for message in reversed(history) if message.role == "user"), None)
        response_language = resolve_response_language(last_user_content, None)
        answer_parts: list[str] = []
        try:
            async for event, payload in self._agent_service.reply(
                conversation_id, staff_id, content, history, response_language
            ):
                if event == "token":
                    answer_parts.append(payload["content"])
                yield event, payload
                if event in {"confirmation_required", "form_required"}:
                    await self._runs.await_confirmation(run)
                    logger.info("agent_run_awaiting_confirmation agent_run_id=%s", run.id)
                    return
            assistant = await self._messages.create(conversation_id, "assistant", "".join(answer_parts))
            await self._runs.complete(run)
            logger.info("agent_run_completed agent_run_id=%s conversation_id=%s", run.id, conversation_id)
            yield "done", {"message_id": str(assistant.id), "conversation_id": str(conversation_id)}
        except Exception:
            await self._runs.fail(run, "Agent execution failed")
            logger.exception("agent_run_failed agent_run_id=%s conversation_id=%s", run.id, conversation_id)
            raise

    async def confirm_tool(
        self,
        conversation_id: uuid.UUID,
        staff_id: str,
        action: str,
        response_language: ResponseLanguage,
        response: dict[str, object] | None = None,
        form_name: str | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, str]]]:
        """确认或取消当前会话唯一等待用户操作的 Tool。"""
        await self._require_conversation(conversation_id, staff_id, response_language)
        run = await self._runs.get_awaiting_confirmation(conversation_id)
        if run is None:
            raise DomainError("TOOL_CONFIRMATION_NOT_FOUND", "No tool confirmation is pending", status.HTTP_409_CONFLICT)
        history = await self._messages.list(conversation_id)
        last_user_content = next((message.content for message in reversed(history) if message.role == "user"), None)
        response_language = resolve_response_language(last_user_content, None)
        if action == "respond" and form_name == "danaan-base-context":
            await save_danaan_base_context_from_form(self._memory_service, staff_id, response)
            logger.info("danaan_base_context_saved staff_id=%s", staff_id)
        answer_parts: list[str] = []
        try:
            async for event, payload in self._agent_service.resume(
                conversation_id, staff_id, action, history, response_language, response
            ):
                if event == "token":
                    answer_parts.append(payload["content"])
                yield event, payload
                if event in {"confirmation_required", "form_required"}:
                    await self._runs.await_confirmation(run)
                    return
            assistant = await self._messages.create(conversation_id, "assistant", "".join(answer_parts))
            await self._runs.complete(run)
            yield "done", {"message_id": str(assistant.id), "conversation_id": str(conversation_id)}
        except Exception:
            await self._runs.fail(run, "Agent execution failed")
            logger.exception("tool_confirmation_failed agent_run_id=%s", run.id)
            raise

    async def _require_conversation(
        self, conversation_id: uuid.UUID, staff_id: str, response_language: ResponseLanguage
    ):
        conversation = await self._conversations.get(conversation_id, staff_id)
        if conversation is None:
            logger.warning("conversation_not_found conversation_id=%s staff_id=%s", conversation_id, staff_id)
            raise DomainError(
                "CONVERSATION_NOT_FOUND",
                "Conversation not found",
                status.HTTP_404_NOT_FOUND,
            )
        return conversation

    def _conversation_payload(self, conversation_id: uuid.UUID, title: str | None, created_at) -> dict[str, str | None]:
        return {"id": str(conversation_id), "title": title, "created_at": created_at.isoformat()}
