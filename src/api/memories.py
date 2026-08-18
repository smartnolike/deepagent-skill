"""Explicit staff-memory API routes."""

# 长期记忆必须由调用方显式写入，禁止把整段聊天自动持久化为记忆。

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from api.schemas.memory import MemoryRequest
from core.auth import require_api_token
from services.memory_service import MemoryService

router = APIRouter(prefix="/api/memories", dependencies=[Depends(require_api_token)])


def _service(request: Request) -> MemoryService:
    return request.app.state.memory_service


@router.put("/{key}")
async def put_memory(key: str, payload: MemoryRequest, service: MemoryService = Depends(_service)) -> dict:
    if key != payload.key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Memory key must match request path",
        )
    return await service.put(payload.staff_id, key, payload.value)


@router.get("")
async def list_memories(staff_id: str, service: MemoryService = Depends(_service)) -> list[dict]:
    return await service.list(staff_id)


@router.delete("/{key}", status_code=204)
async def delete_memory(key: str, staff_id: str, service: MemoryService = Depends(_service)) -> Response:
    await service.delete(staff_id, key)
    return Response(status_code=204)
