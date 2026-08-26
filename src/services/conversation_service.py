"""Conversation business operations."""

from __future__ import annotations

# 会话服务只协调持久化与 Agent 生命周期，Agent 推理期间不持有数据库事务。

import uuid
import logging
import asyncio
from collections.abc import AsyncIterator

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from agent.harness_service import DeepAgentHarnessService
from common.language import ResponseLanguage
from common.language import resolve_response_language
from core.errors import DomainError
from database.models.agent.agent_run import AgentRun
from database.models.agent.tool_confirmation import ToolConfirmation
from repositories.agent_run_repository import AgentRunRepository
from repositories.conversation_repository import ConversationRepository
from repositories.message_repository import MessageRepository
from repositories.tool_confirmation_repository import ToolConfirmationRepository
from repositories.script_artifact_repository import ScriptArtifactRepository
from services.danaan_memory import save_danaan_base_context_from_form
from services.memory_service import MemoryService

logger = logging.getLogger(__name__)
_SENSITIVE_ARGUMENT_KEY_PARTS = frozenset({"password", "secret", "token", "authorization", "credential", "api_key"})


class ConversationService:
    """Coordinate persisted chat history, Agent execution, and run lifecycle."""

    def __init__(
        self, session: AsyncSession, agent_service: DeepAgentHarnessService, memory_service: MemoryService
    ) -> None:
        self._session = session
        self._conversations = ConversationRepository(session)
        self._messages = MessageRepository(session)
        self._runs = AgentRunRepository(session)
        self._confirmations = ToolConfirmationRepository(session)
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

    async def artifact(self, conversation_id: uuid.UUID, artifact_id: uuid.UUID, staff_id: str, response_language: ResponseLanguage):
        await self._require_conversation(conversation_id, staff_id, response_language)
        artifact = await ScriptArtifactRepository(self._session).get(artifact_id, conversation_id)
        if artifact is None:
            raise DomainError("ARTIFACT_NOT_FOUND", "Artifact not found", status.HTTP_404_NOT_FOUND)
        return artifact

    async def tool_confirmations(
        self,
        conversation_id: uuid.UUID,
        staff_id: str,
        response_language: ResponseLanguage,
        decision: str | None = "pending",
    ) -> list[dict[str, object]]:
        """Return persisted confirmation cards so a reloaded UI can restore pending approvals."""
        await self._require_conversation(conversation_id, staff_id, response_language)
        confirmations = await self._confirmations.list(conversation_id, decision)
        return [self._confirmation_payload(item) for item in confirmations]

    async def send(
        self, conversation_id: uuid.UUID, staff_id: str, content: str, response_language: ResponseLanguage
    ) -> AsyncIterator[tuple[str, dict[str, object]]]:
        await self._require_conversation(conversation_id, staff_id, response_language)
        previous_history = await self._messages.list(conversation_id)
        previous_language = _language_from_history(previous_history)
        response_language = resolve_response_language(content, previous_language=previous_language)
        user_message = await self._messages.create(conversation_id, "user", content)
        run = await self._runs.create(conversation_id, user_message.id)
        logger.info("agent_run_started agent_run_id=%s conversation_id=%s staff_id=%s", run.id, conversation_id, staff_id)
        history = await self._messages.list(conversation_id)
        answer_parts: list[str] = []
        try:
            async for event, payload in self._agent_service.reply(
                conversation_id, staff_id, run.id, content, history, response_language
            ):
                if event == "token":
                    answer_parts.append(payload["content"])
                if event in {"confirmation_required", "form_required"}:
                    if event == "confirmation_required":
                        confirmation = await self._create_tool_confirmation(conversation_id, run, payload)
                        payload = {key: value for key, value in payload.items() if key != "arguments"}
                        payload = {**payload, **self._confirmation_payload(confirmation)}
                    await self._runs.await_confirmation(run)
                    logger.info("agent_run_awaiting_confirmation agent_run_id=%s", run.id)
                    yield event, payload
                    return
                yield event, payload
            assistant = await self._messages.create(conversation_id, "assistant", "".join(answer_parts))
            await self._runs.complete(run)
            logger.info("agent_run_completed agent_run_id=%s conversation_id=%s", run.id, conversation_id)
            yield "done", {"message_id": str(assistant.id), "conversation_id": str(conversation_id)}
        except asyncio.CancelledError:
            await self._mark_run_cancelled(run, conversation_id)
            raise
        except Exception as exc:
            error_id = str(uuid.uuid4())
            logger.exception(
                "agent_run_failed",
                extra={
                    "fields": {
                        "agent_run_id": str(run.id),
                        "conversation_id": str(conversation_id),
                        "staff_id": staff_id,
                        "error_id": error_id,
                        "error_type": type(exc).__name__,
                    }
                },
            )
            await self._mark_run_failed(run, conversation_id, error_id)
            raise

    async def confirm_tool(
        self,
        conversation_id: uuid.UUID,
        staff_id: str,
        action: str,
        response_language: ResponseLanguage,
        response: dict[str, object] | None = None,
        form_name: str | None = None,
        confirmation_id: uuid.UUID | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, object]]]:
        """确认或取消当前会话唯一等待用户操作的 Tool。"""
        await self._require_conversation(conversation_id, staff_id, response_language)
        run = await self._runs.get_awaiting_confirmation(conversation_id)
        if run is None:
            raise DomainError("TOOL_CONFIRMATION_NOT_PENDING", "No tool confirmation is pending", status.HTTP_409_CONFLICT)
        confirmation: ToolConfirmation | None = None
        if action != "respond":
            if confirmation_id is None:
                raise DomainError("TOOL_CONFIRMATION_ID_REQUIRED", "confirmation_id is required", status.HTTP_422_UNPROCESSABLE_ENTITY)
            confirmation = await self._confirmations.get(confirmation_id, conversation_id)
            if confirmation is None:
                raise DomainError("TOOL_CONFIRMATION_NOT_FOUND", "Tool confirmation not found", status.HTTP_404_NOT_FOUND)
            if confirmation.decision != "pending":
                raise DomainError(
                    "TOOL_CONFIRMATION_ALREADY_DECIDED",
                    "Tool confirmation has already been decided",
                    status.HTTP_409_CONFLICT,
                )
            if run.id != confirmation.agent_run_id:
                raise DomainError("TOOL_CONFIRMATION_NOT_PENDING", "Tool confirmation is no longer pending", status.HTTP_409_CONFLICT)
        history = await self._messages.list(conversation_id)
        response_language = _language_from_history(history) or response_language
        if action == "respond" and form_name == "danaan-base-context":
            await save_danaan_base_context_from_form(self._memory_service, staff_id, response)
            logger.info("danaan_base_context_saved staff_id=%s", staff_id)
        if confirmation is not None:
            confirmation = await self._confirmations.decide(confirmation, staff_id, action)
        await self._runs.resume(run)
        if confirmation is not None:
            logger.info(
                "tool_confirmation_decided confirmation_id=%s agent_run_id=%s action=%s",
                confirmation.id,
                run.id,
                action,
            )
        answer_parts: list[str] = []
        try:
            async for event, payload in self._agent_service.resume(
                conversation_id, staff_id, run.id, action, history, response_language, response
            ):
                if event == "token":
                    answer_parts.append(payload["content"])
                if event in {"confirmation_required", "form_required"}:
                    if action == "approve" and confirmation is not None:
                        await self._confirmations.mark_succeeded(confirmation)
                    if event == "confirmation_required":
                        next_confirmation = await self._create_tool_confirmation(conversation_id, run, payload)
                        payload = {key: value for key, value in payload.items() if key != "arguments"}
                        payload = {**payload, **self._confirmation_payload(next_confirmation)}
                    await self._runs.await_confirmation(run)
                    yield event, payload
                    return
                yield event, payload
            assistant = await self._messages.create(conversation_id, "assistant", "".join(answer_parts))
            await self._runs.complete(run)
            if action == "approve" and confirmation is not None:
                await self._confirmations.mark_succeeded(confirmation)
            yield "done", {"message_id": str(assistant.id), "conversation_id": str(conversation_id)}
        except asyncio.CancelledError:
            await self._mark_run_cancelled(run, conversation_id)
            if action == "approve" and confirmation is not None:
                await self._confirmations.mark_cancelled(confirmation)
            raise
        except Exception as exc:
            error_id = str(uuid.uuid4())
            logger.exception(
                "tool_confirmation_failed",
                extra={
                    "fields": {
                        "agent_run_id": str(run.id),
                        "conversation_id": str(conversation_id),
                        "staff_id": staff_id,
                        "error_id": error_id,
                        "error_type": type(exc).__name__,
                    }
                },
            )
            await self._mark_run_failed(run, conversation_id, error_id)
            if action == "approve" and confirmation is not None:
                await self._confirmations.mark_failed(confirmation)
            raise

    async def _create_tool_confirmation(
        self,
        conversation_id: uuid.UUID,
        run: AgentRun,
        payload: dict[str, object],
    ) -> ToolConfirmation:
        """Persist the Agent interrupt before exposing it to the client by SSE."""
        tool_name = str(payload.get("tool_name", "unknown"))
        description = str(payload.get("description", "Confirm tool execution"))
        raw_arguments = payload.get("arguments")
        display_arguments = _redact_display_arguments(raw_arguments)
        confirmation = await self._confirmations.create(
            conversation_id,
            run.id,
            tool_name,
            description,
            display_arguments,
        )
        logger.info(
            "tool_confirmation_created confirmation_id=%s agent_run_id=%s tool_name=%s",
            confirmation.id,
            run.id,
            tool_name,
        )
        return confirmation

    def _confirmation_payload(self, confirmation: ToolConfirmation) -> dict[str, object]:
        """Translate the persistent approval record into the stable API card format."""
        return {
            "confirmation_id": str(confirmation.id),
            "tool_name": confirmation.tool_name,
            "description": confirmation.description,
            "display_arguments": confirmation.display_arguments,
            "decision": confirmation.decision,
            "execution_status": confirmation.execution_status,
            "created_at": confirmation.created_at.isoformat(),
            "decided_at": confirmation.decided_at.isoformat() if confirmation.decided_at is not None else None,
        }

    async def _mark_run_failed(self, run: AgentRun, conversation_id: uuid.UUID, error_id: str) -> None:
        """Persist a safe failure marker without hiding the original execution exception."""
        try:
            await self._runs.fail(run, f"Agent execution failed; error_id={error_id}")
        except Exception:
            logger.exception(
                "agent_run_failure_persist_failed",
                extra={"fields": {"agent_run_id": str(run.id), "conversation_id": str(conversation_id), "error_id": error_id}},
            )

    async def _mark_run_cancelled(self, run: AgentRun, conversation_id: uuid.UUID) -> None:
        """Persist a best-effort cancellation marker after an SSE client disconnects."""
        try:
            await self._runs.cancel(run)
            logger.info(
                "agent_run_cancelled",
                extra={"fields": {"agent_run_id": str(run.id), "conversation_id": str(conversation_id)}},
            )
        except Exception:
            logger.exception(
                "agent_run_cancellation_persist_failed",
                extra={"fields": {"agent_run_id": str(run.id), "conversation_id": str(conversation_id)}},
            )

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


def _redact_display_arguments(value: object) -> dict[str, object]:
    """Return JSON-safe Tool arguments while removing credential-like fields from the UI and database."""
    if not isinstance(value, dict):
        return {}
    return {str(key): _redact_display_value(str(key), item) for key, item in value.items()}


def _redact_display_value(key: str, value: object) -> object:
    """Recursively redact known secret-shaped argument names without altering ordinary request fields."""
    normalized_key = key.lower().replace("-", "_")
    if any(part in normalized_key for part in _SENSITIVE_ARGUMENT_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(child_key): _redact_display_value(str(child_key), child) for child_key, child in value.items()}
    if isinstance(value, list):
        return [_redact_display_value(key, item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _language_from_history(messages: list[object]) -> ResponseLanguage | None:
    """Find the active user language while letting technical-value turns inherit it."""
    language: ResponseLanguage | None = None
    for message in messages:
        if getattr(message, "role", None) == "user":
            language = resolve_response_language(getattr(message, "content", None), previous_language=language)
    return language
