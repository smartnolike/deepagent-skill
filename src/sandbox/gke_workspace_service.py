"""Artifacts and lifecycle for conversation directories in the fixed GKE Sandbox."""

from __future__ import annotations

import posixpath
import uuid
from datetime import UTC, datetime, timedelta

from config.sandbox_settings import GkeAgentSandboxSettings
from sandbox.gke_backend import GkeSandboxBackend


class GkeWorkspaceService:
    def __init__(self, settings: GkeAgentSandboxSettings, backend: GkeSandboxBackend) -> None:
        self._settings = settings
        self._backend = backend

    @property
    def retention_seconds(self) -> int:
        return self._settings.workspace_retention_seconds

    @property
    def artifact_expiry(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=self.retention_seconds)

    @staticmethod
    def normalize_output_path(path: str) -> str:
        if path.startswith("/output/"):
            path = f"/workspace{path}"
        normalized = posixpath.normpath(path)
        if not normalized.startswith("/workspace/output/"):
            raise ValueError("Artifacts must be published from /workspace/output")
        return normalized

    def read_artifact(self, staff_id: str, conversation_id: uuid.UUID, path: str) -> bytes:
        return self._backend.read_file_for(staff_id, conversation_id, self.normalize_output_path(path))

    def delete_workspace(self, staff_id: str, conversation_id: uuid.UUID) -> None:
        self._backend.delete_workspace_for(staff_id, conversation_id)
