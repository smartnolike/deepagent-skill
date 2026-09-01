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
from sandbox.gke_workspace_service import GkeWorkspaceService

_MAX_ARTIFACT_BYTES = 20 * 1024 * 1024


def create_publish_artifact_tool(
    session_factory: async_sessionmaker[AsyncSession], workspace_service: GkeWorkspaceService
) -> StructuredTool:
    async def publish_artifact(path: str, filename: str | None = None) -> dict[str, object]:
        path = workspace_service.normalize_output_path(path)
        thread_id = (ensure_config().get("configurable") or {}).get("thread_id")
        if not isinstance(thread_id, str):
            raise RuntimeError("publish_artifact requires a conversation thread")
        conversation_id = uuid.UUID(thread_id)
        configurable = ensure_config().get("configurable") or {}
        staff_id = configurable.get("staff_id")
        if not isinstance(staff_id, str):
            raise RuntimeError("publish_artifact requires a staff ID")
        async with session_factory() as session:
            content = await asyncio.to_thread(workspace_service.read_artifact, staff_id, conversation_id, path)
            if len(content) > _MAX_ARTIFACT_BYTES:
                raise ValueError("Artifact exceeds the 20 MiB download limit")
            download_name = PurePosixPath(filename or path).name.replace('"', "_").replace("\\", "_")
            if not download_name or any(character in download_name for character in ("\r", "\n", "\x00")):
                raise ValueError("Artifact filename is invalid")
            artifact = await SandboxArtifactRepository(session).create(
                SandboxArtifact(
                    conversation_id=conversation_id,
                    sandbox_path=path,
                    filename=download_name[:255],
                    content_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
                    size_bytes=len(content),
                    expires_at=workspace_service.artifact_expiry,
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
