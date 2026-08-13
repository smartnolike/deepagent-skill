"""Async session maker and FastAPI dependency."""

# Session 生命周期绑定单个 HTTP 请求，不能保存到全局单例或 Agent 对象。

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped session without retaining a transaction."""
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session
