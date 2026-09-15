"""Independent TTL cleanup for directories in the fixed GKE Sandbox."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repositories.conversation_workspace_repository import ConversationWorkspaceRepository
from sandbox.gke_workspace_service import GkeWorkspaceService

logger = logging.getLogger(__name__)


async def cleanup_expired_gke_workspaces(
    session_factory: async_sessionmaker[AsyncSession], workspace_service: GkeWorkspaceService
) -> None:
    """Delete only directories whose own activity TTL has elapsed."""
    cutoff = datetime.now(UTC) - timedelta(seconds=workspace_service.retention_seconds)
    async with session_factory() as session:
        repository = ConversationWorkspaceRepository(session)
        for workspace in await repository.expired(cutoff):
            try:
                await asyncio.to_thread(workspace_service.delete_workspace, workspace.staff_id, workspace.conversation_id)
                await repository.delete(workspace)
            except Exception as exc:
                logger.warning(
                    "gke_workspace_cleanup_failed conversation_id=%s error_type=%s",
                    workspace.conversation_id,
                    type(exc).__name__,
                )


async def gke_workspace_cleanup_loop(
    session_factory: async_sessionmaker[AsyncSession], workspace_service: GkeWorkspaceService
) -> None:
    while True:
        await cleanup_expired_gke_workspaces(session_factory, workspace_service)
        await asyncio.sleep(3600)
