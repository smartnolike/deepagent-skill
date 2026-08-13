"""Conversation REST and SSE routes."""

# Router 仅处理协议转换；会话校验、数据库操作和 Agent 调用均在 Service 层完成。

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse

from src.core.auth import require_api_token
from src.database.session import get_db_session
from src.services.conversation_service import ConversationService

router = APIRouter(prefix="/api/conversations", dependencies=[Depends(require_api_token)])


def _service(request: Request, session=Depends(get_db_session)) -> ConversationService:
    return ConversationService(session, request.app.state.agent_service)


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
async def get_conversation(conversation_id: uuid.UUID, staff_id: str, service: ConversationService = Depends(_service)) -> dict:
    return await service.get(conversation_id, staff_id)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, staff_id: str, service: ConversationService = Depends(_service)) -> Response:
    await service.delete(conversation_id, staff_id)
    return Response(status_code=204)


@router.get("/{conversation_id}/messages")
async def list_messages(conversation_id: uuid.UUID, staff_id: str, service: ConversationService = Depends(_service)) -> list[dict]:
    return await service.messages(conversation_id, staff_id)


@router.post("/{conversation_id}/messages")
async def send_message(conversation_id: uuid.UUID, payload: dict, service: ConversationService = Depends(_service)) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        try:
            async for event, data in service.send(conversation_id, payload["staff_id"], payload["content"]):
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception:
            yield 'event: error\ndata: {"code":"AGENT_ERROR","message":"Agent execution failed"}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream")
