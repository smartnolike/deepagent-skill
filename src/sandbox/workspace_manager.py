"""Small facade that resolves a conversation to its selected workspace backend."""

from __future__ import annotations

import uuid
from pathlib import Path

from langchain_core.runnables.config import ensure_config

from config.sandbox_settings import SandboxSettings
from sandbox.artifact_service import WorkspaceArtifactService
from sandbox.conversation_sandbox_backend import ConversationSandboxBackend
from sandbox.session_store import WorkspaceReference, WorkspaceSessionStore
from sandbox.workspace_providers import (
    FilesystemWorkspaceProvider,
    GkeWorkspaceProvider,
    LocalShellWorkspaceProvider,
    WorkspaceProvider,
)


class WorkspaceManager:
    """Coordinate provider selection; provider and persistence details live elsewhere."""

    def __init__(self, settings: SandboxSettings, skills_root: Path, psycopg_url: str) -> None:
        self._settings = settings
        self._sessions = WorkspaceSessionStore(psycopg_url)
        self._artifacts = WorkspaceArtifactService()
        resolved_skills_root = skills_root.resolve()
        self._providers: dict[str, WorkspaceProvider] = {
            "filesystem": FilesystemWorkspaceProvider(resolved_skills_root),
            "local_shell": LocalShellWorkspaceProvider(settings.local_shell, resolved_skills_root),
        }
        if settings.gke is not None:
            self._providers["gke_backend"] = GkeWorkspaceProvider(settings.gke)
        self._deepagents_backend = (
            self._selected_provider.backend()
            if settings.provider == "filesystem"
            else ConversationSandboxBackend(self)
        )

    @property
    def skills_path(self) -> str:
        return self._selected_provider.skills_path

    @property
    def supports_artifacts(self) -> bool:
        return self._selected_provider.supports_artifacts

    @property
    def deepagents_backend(self):
        """Return the initialized BackendProtocol required by DeepAgents 0.7+."""
        return self._deepagents_backend

    def sandbox_backend_for_current_thread(self):
        """Resolve the execution backend lazily from the active LangGraph thread."""
        if self._settings.provider == "filesystem":
            raise RuntimeError("FilesystemBackend does not support sandbox execution")
        return self._selected_provider.backend(self._ensure_workspace(self._thread_id()))

    def download_artifact(self, reference: WorkspaceReference, path: str) -> bytes:
        return self._artifacts.read(reference, self._provider(reference.provider), path)

    def normalize_artifact_path(self, path: str) -> str:
        return self._artifacts.normalize_path(path)

    def release(self, conversation_id: uuid.UUID) -> None:
        with self._sessions.locked(conversation_id) as connection:
            reference = self._sessions.get_active(conversation_id, connection)
            if reference is not None:
                self._release_and_expire(reference, connection)

    @property
    def _selected_provider(self) -> WorkspaceProvider:
        return self._provider(self._settings.provider)

    def _ensure_workspace(self, conversation_id: uuid.UUID) -> WorkspaceReference:
        provider = self._selected_provider
        with self._sessions.locked(conversation_id) as connection:
            existing = self._sessions.get_active(conversation_id, connection)
            if self._reusable(existing, provider):
                assert existing is not None
                self._sessions.touch(existing.id, connection)
                return existing
            if existing is not None:
                self._release_and_expire(existing, connection)
            allocation = provider.create(conversation_id)
            return self._sessions.create(
                conversation_id,
                provider.name,
                allocation.workspace_reference,
                allocation.namespace,
                allocation.expires_at,
                connection,
            )

    def _reusable(self, reference: WorkspaceReference | None, provider: WorkspaceProvider) -> bool:
        if reference is None or reference.provider != provider.name:
            return False
        idle_ttl = (
            self._settings.gke.idle_ttl_seconds
            if provider.name == "gke_backend" and self._settings.gke
            else None
        )
        return not self._sessions.is_expired(reference, idle_ttl) and provider.reusable(reference)

    def _release_and_expire(self, reference: WorkspaceReference, connection) -> None:
        try:
            self._provider(reference.provider).release(reference)
        except Exception:
            pass
        self._sessions.expire(reference.id, connection)

    def _provider(self, name: str) -> WorkspaceProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise RuntimeError(f"Unsupported workspace provider: {name}") from exc

    @staticmethod
    def _thread_id() -> uuid.UUID:
        thread_id = (ensure_config().get("configurable") or {}).get("thread_id")
        if not isinstance(thread_id, str):
            raise RuntimeError("Workspace backend requires configurable.thread_id")
        return uuid.UUID(thread_id)


__all__ = ["WorkspaceManager", "WorkspaceReference"]
