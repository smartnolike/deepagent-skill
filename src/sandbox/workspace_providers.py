"""Provider-specific workspace creation, execution, files, and cleanup."""

from __future__ import annotations

import shutil
import stat
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from deepagents.backends import FilesystemBackend, LocalShellBackend

from config.sandbox_settings import GkeAgentSandboxSettings, LocalShellSettings
from sandbox.gke_backend import GkeSandboxBackend
from sandbox.gke_client import GkeSandboxClient
from sandbox.session_store import WorkspaceReference


@dataclass(frozen=True)
class WorkspaceAllocation:
    workspace_reference: str
    namespace: str | None
    expires_at: datetime | None


class WorkspaceProvider(Protocol):
    name: str
    skills_path: str
    supports_artifacts: bool

    def create(self, conversation_id: uuid.UUID) -> WorkspaceAllocation: ...
    def backend(self, reference: WorkspaceReference | None = None): ...
    def read_output(self, reference: WorkspaceReference, path: str) -> bytes: ...
    def release(self, reference: WorkspaceReference) -> None: ...
    def reusable(self, reference: WorkspaceReference) -> bool: ...


class FilesystemWorkspaceProvider:
    name = "filesystem"
    skills_path = "/"
    supports_artifacts = False

    def __init__(self, skills_root: Path) -> None:
        self._skills_root = skills_root

    def backend(self, reference: WorkspaceReference | None = None) -> FilesystemBackend:
        return FilesystemBackend(root_dir=self._skills_root)


class LocalShellWorkspaceProvider:
    name = "local_shell"
    skills_path = "/skill-packages"
    supports_artifacts = True

    def __init__(self, settings: LocalShellSettings, skills_root: Path) -> None:
        self._settings = settings
        self._skills_root = skills_root

    def create(self, conversation_id: uuid.UUID) -> WorkspaceAllocation:
        root = (self._settings.workspace_root / str(conversation_id)).resolve()
        if not root.exists():
            root.mkdir(parents=True, exist_ok=False)
            shutil.copytree(self._skills_root, root / "skill-packages")
            self._make_read_only(root / "skill-packages")
            (root / "work").mkdir()
            (root / "output").mkdir()
        return WorkspaceAllocation(str(root), None, None)

    def backend(self, reference: WorkspaceReference | None = None) -> LocalShellBackend:
        assert reference is not None
        root = Path(reference.workspace_reference)
        return LocalShellBackend(
            root_dir=root,
            virtual_mode=True,
            timeout=self._settings.timeout_seconds,
            max_output_bytes=self._settings.max_output_bytes,
            inherit_env=False,
            env={
                "PATH": f"{Path(sys.executable).parent}:/usr/local/bin:/usr/bin:/bin",
                "HOME": str(root),
                "DEEPAGENT_WORKSPACE": str(root),
            },
        )

    def read_output(self, reference: WorkspaceReference, path: str) -> bytes:
        root = Path(reference.workspace_reference).resolve()
        candidate = (root / path.removeprefix("/workspace/")).resolve()
        if not candidate.is_relative_to(root / "output"):
            raise ValueError("Artifact path escapes the local output directory")
        return candidate.read_bytes()

    def release(self, reference: WorkspaceReference) -> None:
        workspace_root = self._settings.workspace_root.resolve()
        target = Path(reference.workspace_reference).resolve()
        if target != workspace_root and target.is_relative_to(workspace_root):
            self._make_writable(target / "skill-packages")
            shutil.rmtree(target, ignore_errors=True)

    def reusable(self, reference: WorkspaceReference) -> bool:
        return Path(reference.workspace_reference).is_dir()

    @staticmethod
    def _make_read_only(directory: Path) -> None:
        for path in [directory, *directory.rglob("*")]:
            path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))

    @staticmethod
    def _make_writable(directory: Path) -> None:
        if not directory.exists():
            return
        for path in [directory, *directory.rglob("*")]:
            path.chmod(path.stat().st_mode | stat.S_IWUSR)


class GkeWorkspaceProvider:
    name = "gke_backend"
    skills_path = "/workspace/skill-packages"
    supports_artifacts = True

    def __init__(self, settings: GkeAgentSandboxSettings) -> None:
        self._settings = settings
        self._client = GkeSandboxClient(settings)

    def create(self, conversation_id: uuid.UUID) -> WorkspaceAllocation:
        sandbox = self._client.create(conversation_id)
        claim_name = str(getattr(sandbox, "claim_name", None) or getattr(sandbox, "sandbox_id"))
        return WorkspaceAllocation(
            claim_name,
            self._settings.namespace,
            datetime.now(UTC) + timedelta(seconds=self._settings.absolute_ttl_seconds),
        )

    def backend(self, reference: WorkspaceReference | None = None) -> GkeSandboxBackend:
        assert reference is not None
        sandbox = self._client.get(reference.workspace_reference, reference.namespace)
        return GkeSandboxBackend(sandbox, self._settings.command_timeout_seconds)

    def read_output(self, reference: WorkspaceReference, path: str) -> bytes:
        return self.backend(reference).read_file(path)

    def release(self, reference: WorkspaceReference) -> None:
        self._client.terminate(reference.workspace_reference, reference.namespace)

    def reusable(self, reference: WorkspaceReference) -> bool:
        try:
            self._client.get(reference.workspace_reference, reference.namespace)
            return True
        except Exception:
            return False
