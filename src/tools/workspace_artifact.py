"""Publish temporary files from a conversation workspace to the chat UI."""

from __future__ import annotations

import asyncio
import mimetypes
import uuid
from pathlib import PurePosixPath

from langchain_core.runnables.config import ensure_config
from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models.agent.sandbox_artifact import SandboxArtifact
from repositories.sandbox_artifact_repository import SandboxArtifactRepository
from repositories.sandbox_session_repository import SandboxSessionRepository
from sandbox.workspace_manager import WorkspaceManager, WorkspaceReference

_MAX_ARTIFACT_BYTES = 20 * 1024 * 1024


def create_publish_artifact_tool(
    session_factory: async_sessionmaker[AsyncSession], workspace_manager: WorkspaceManager
) -> StructuredTool:
    async def publish_artifact(path: str, filename: str | None = None) -> dict[str, object]:
        path = workspace_manager.normalize_artifact_path(path)
        if not path.startswith("/workspace/output/"):
            raise ValueError("Only files under /workspace/output may be published")
        thread_id = (ensure_config().get("configurable") or {}).get("thread_id")
        if not isinstance(thread_id, str):
            raise RuntimeError("publish_artifact requires a conversation thread")
        conversation_id = uuid.UUID(thread_id)
        async with session_factory() as session:
            workspace = await SandboxSessionRepository(session).get(conversation_id)
            if workspace is None or workspace.status != "active":
                raise RuntimeError("No active workspace exists for this conversation")
            reference = WorkspaceReference(
                workspace.id, workspace.provider, workspace.workspace_reference, workspace.namespace, workspace.expires_at
            )
            content = await asyncio.to_thread(workspace_manager.download_artifact, reference, path)
            if len(content) > _MAX_ARTIFACT_BYTES:
                raise ValueError("Artifact exceeds the 20 MiB download limit")
            download_name = PurePosixPath(filename or path).name.replace('"', "_").replace("\\", "_")
            if not download_name or any(character in download_name for character in ("\r", "\n", "\x00")):
                raise ValueError("Artifact filename is invalid")
            artifact = await SandboxArtifactRepository(session).create(
                SandboxArtifact(
                    conversation_id=conversation_id,
                    sandbox_session_id=workspace.id,
                    sandbox_path=path,
                    filename=download_name[:255],
                    content_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
                    size_bytes=len(content),
                    expires_at=workspace.expires_at,
                )
            )
        return {"artifact_id": str(artifact.id), "filename": artifact.filename, "size_bytes": artifact.size_bytes}

    return StructuredTool.from_function(
        coroutine=publish_artifact,
        name="publish_artifact",
        description=(
            "Publish a generated file under /output (or /workspace/output) for the current user to download "
            "before the conversation workspace expires."
        ),
    )
