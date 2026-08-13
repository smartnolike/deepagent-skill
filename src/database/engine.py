"""Async SQLAlchemy engine factory."""

# 业务查询固定走 asyncpg，避免与 psycopg checkpointer 混用连接池。

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.config.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the application-owned async database engine."""
    return create_async_engine(settings.async_sqlalchemy_url, pool_pre_ping=True)
