"""Conversation REST and SSE routes."""

# Router 仅处理协议转换；会话校验、数据库操作和 Agent 调用均在 Service 层完成。

import json
import uuid
import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse

from api.schemas.conversation_title import ConversationTitleRequest
from common.language import resolve_response_language
from core.auth import require_api_token
from core.errors import DomainError
from core.request_context import bind_request_id
from database.session import get_db_session
from services.conversation_service import ConversationService

router = APIRouter(prefix="/api/conversations", dependencies=[Depends(require_api_token)])
logger = logging.getLogger(__name__)


def _service(request: Request, session=Depends(get_db_session)) -> ConversationService:
    return ConversationService(session, request.app.state.agent_service, request.app.state.memory_service)


@router.post("")
async def create_conversation(payload: dict, service: ConversationService = Depends(_service)) -> dict:
    return await service.create(payload["staff_id"], payload.get("title"))


@router.get("")
async def list_conversations(
    staff_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: ConversationService = Depends(_service),
) -> dict:
    return await service.list(staff_id, page, page_size)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, staff_id: str, accept_language: str | None = Header(default=None), service: ConversationService = Depends(_service)
) -> dict:
    return await service.get(conversation_id, staff_id, resolve_response_language(None, accept_language))


@router.patch("/{conversation_id}")
async def update_conversation_title(
    conversation_id: uuid.UUID,
    payload: ConversationTitleRequest,
    accept_language: str | None = Header(default=None),
    service: ConversationService = Depends(_service),
) -> dict:
    """更新会话标题；title 为 null 时清空标题。"""
    return await service.update_title(
        conversation_id,
        payload.staff_id,
        payload.title,
        resolve_response_language(None, accept_language),
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID, staff_id: str, accept_language: str | None = Header(default=None), service: ConversationService = Depends(_service)
) -> Response:
    await service.delete(conversation_id, staff_id, resolve_response_language(None, accept_language))
    return Response(status_code=204)


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: uuid.UUID, staff_id: str, accept_language: str | None = Header(default=None), service: ConversationService = Depends(_service)
) -> list[dict]:
    return await service.messages(conversation_id, staff_id, resolve_response_language(None, accept_language))


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    payload: dict,
    request: Request,
    accept_language: str | None = Header(default=None),
    service: ConversationService = Depends(_service),
) -> StreamingResponse:
    response_language = resolve_response_language(payload["content"], accept_language)
    request_id = request.state.request_id

    async def events() -> AsyncIterator[str]:
        with bind_request_id(request_id):
            try:
                async for event, data in service.send(conversation_id, payload["staff_id"], payload["content"], response_language):
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                logger.info("sse_client_disconnected", extra={"fields": {"conversation_id": str(conversation_id)}})
                raise
            except Exception as exc:
                error_id = str(uuid.uuid4())
                logger.exception(
                    "sse_message_stream_failed",
                    extra={
                        "fields": {
                            "conversation_id": str(conversation_id),
                            "error_id": error_id,
                            "error_type": type(exc).__name__,
                        }
                    },
                )
                data = {"code": "AGENT_ERROR", "message": "Agent execution failed", "error_id": error_id}
                yield f"event: error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/{conversation_id}/tool-confirmations")
async def confirm_tool(
    conversation_id: uuid.UUID,
    payload: dict,
    request: Request,
    accept_language: str | None = Header(default=None),
    service: ConversationService = Depends(_service),
) -> StreamingResponse:
    """Resume a structured form interrupt; Tool approvals use the ID-specific endpoint."""
    if payload.get("action") != "respond":
        raise DomainError("INVALID_TOOL_CONFIRMATION", "action must be respond", 422)
    response = payload.get("response")
    if payload.get("action") == "respond" and not isinstance(response, dict):
        raise DomainError("INVALID_FORM_RESPONSE", "response must be an object when action is respond", 422)
    form_name = payload.get("form_name")
    if form_name is not None and not isinstance(form_name, str):
        raise DomainError("INVALID_FORM_NAME", "form_name must be a string", 422)
    response_language = resolve_response_language(None, accept_language)

    request_id = request.state.request_id

    async def events() -> AsyncIterator[str]:
        with bind_request_id(request_id):
            try:
                async for event, data in service.confirm_tool(
                    conversation_id, payload["staff_id"], payload["action"], response_language, response, form_name
                ):
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                logger.info("sse_client_disconnected", extra={"fields": {"conversation_id": str(conversation_id)}})
                raise
            except Exception as exc:
                error_id = str(uuid.uuid4())
                logger.exception(
                    "sse_tool_confirmation_stream_failed",
                    extra={
                        "fields": {
                            "conversation_id": str(conversation_id),
                            "error_id": error_id,
                            "error_type": type(exc).__name__,
                        }
                    },
                )
                data = {"code": "AGENT_ERROR", "message": "Agent execution failed", "error_id": error_id}
                yield f"event: error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/{conversation_id}/tool-confirmations")
async def list_tool_confirmations(
    conversation_id: uuid.UUID,
    staff_id: str,
    decision: str | None = Query(default="pending", pattern="^(pending|approve|reject)$"),
    accept_language: str | None = Header(default=None),
    service: ConversationService = Depends(_service),
) -> dict[str, list[dict[str, object]]]:
    """Restore persisted confirmation cards after a conversation page reload."""
    return {
        "items": await service.tool_confirmations(
            conversation_id,
            staff_id,
            resolve_response_language(None, accept_language),
            decision,
        )
    }


@router.post("/{conversation_id}/tool-confirmations/{confirmation_id}")
async def decide_tool_confirmation(
    conversation_id: uuid.UUID,
    confirmation_id: uuid.UUID,
    payload: dict,
    request: Request,
    accept_language: str | None = Header(default=None),
    service: ConversationService = Depends(_service),
) -> StreamingResponse:
    """Approve or reject one durable Tool confirmation and resume its Agent run once."""
    if payload.get("action") not in {"approve", "reject"}:
        raise DomainError("INVALID_TOOL_CONFIRMATION", "action must be approve or reject", 422)
    response_language = resolve_response_language(None, accept_language)
    request_id = request.state.request_id

    async def events() -> AsyncIterator[str]:
        with bind_request_id(request_id):
            try:
                async for event, data in service.confirm_tool(
                    conversation_id,
                    payload["staff_id"],
                    payload["action"],
                    response_language,
                    confirmation_id=confirmation_id,
                ):
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                logger.info("sse_client_disconnected", extra={"fields": {"conversation_id": str(conversation_id)}})
                raise
            except Exception as exc:
                error_id = str(uuid.uuid4())
                logger.exception(
                    "sse_tool_confirmation_stream_failed",
                    extra={
                        "fields": {
                            "conversation_id": str(conversation_id),
                            "confirmation_id": str(confirmation_id),
                            "error_id": error_id,
                            "error_type": type(exc).__name__,
                        }
                    },
                )
                data = {"code": "AGENT_ERROR", "message": "Agent execution failed", "error_id": error_id}
                yield f"event: error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
