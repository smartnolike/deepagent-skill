"""A DeepAgents 0.7 backend instance that resolves the current conversation lazily."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    SandboxBackendProtocol,
)
from deepagents.backends.sandbox import BaseSandbox

if TYPE_CHECKING:
    from sandbox.workspace_manager import WorkspaceManager


class ConversationSandboxBackend(BaseSandbox):
    """Delegate each operation to the sandbox selected by LangGraph's thread ID."""

    def __init__(self, workspace_manager: "WorkspaceManager") -> None:
        self._workspace_manager = workspace_manager

    @property
    def id(self) -> str:
        return self._delegate().id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return self._delegate().execute(command, timeout=timeout)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return self._delegate().upload_files(files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return self._delegate().download_files(paths)

    def _delegate(self) -> SandboxBackendProtocol:
        backend = self._workspace_manager.sandbox_backend_for_current_thread()
        if not isinstance(backend, SandboxBackendProtocol):
            raise RuntimeError("The selected workspace does not support sandbox execution")
        return backend
