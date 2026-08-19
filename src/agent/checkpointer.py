"""LangGraph PostgreSQL checkpointer lifecycle helper."""

# 使用官方 AsyncPostgresSaver；禁止应用手工创建或修改 checkpoint 内部表。

from contextlib import AbstractAsyncContextManager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from config.settings import Settings


def create_checkpointer_context(settings: Settings) -> AbstractAsyncContextManager[AsyncPostgresSaver]:
    """Create the official psycopg-backed saver context for application lifespan."""
    return AsyncPostgresSaver.from_conn_string(settings.psycopg_url)
