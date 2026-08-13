"""Root API router."""

# 统一挂载受保护的 API 子路由，业务路由不直接操作应用资源。

from fastapi import APIRouter

from .conversations import router as conversations_router
from .memories import router as memories_router

router = APIRouter()
router.include_router(conversations_router)
router.include_router(memories_router)
