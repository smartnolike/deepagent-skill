"""DeepAgents adapter for one shared, pre-deployed GKE Sandbox."""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox
from langchain_core.runnables.config import ensure_config

from config.sandbox_settings import GkeAgentSandboxSettings
from sandbox.gke_client import GkeSandboxClient
from sandbox.gke_runtime_paths import ConversationWorkspacePaths, GkeRuntimePathError, to_runtime_relative_path

_STAFF_ID = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


class GkeSandboxBackend(BaseSandbox):
    """Use one Sandbox while resolving a different directory for each conversation."""

    def __init__(self, settings: GkeAgentSandboxSettings, sandbox: Any | None = None) -> None:
        self._settings = settings
        self._sandbox = sandbox

    @property
    def id(self) -> str:
        return self._settings.sandbox_name

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        paths = self._current_paths()
        mapped = paths.map_command(command)
        prefix = (
            f"mkdir -p {paths.workspace}/work {paths.workspace}/output && "
            f"cd {paths.workspace}/work && export DEEPAGENT_WORKSPACE={paths.workspace}"
        )
        result = self._sandbox_for_use().commands.run(
            f"{prefix} && {mapped}", timeout=timeout or self._settings.command_timeout_seconds
        )
        output = "".join(part for part in (getattr(result, "stdout", ""), getattr(result, "stderr", "")) if part)
        return ExecuteResponse(output=output or "<no output>", exit_code=result.exit_code, truncated=False)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return await asyncio.to_thread(self.execute, command, timeout=timeout)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                runtime_path = to_runtime_relative_path(self._current_paths().physical_path(path))
                self._sandbox_for_use().connector.send_request(
                    "POST", "upload", files={"file": (runtime_path, content)}, timeout=60
                )
                responses.append(FileUploadResponse(path=path))
            except (GkeRuntimePathError, ValueError):
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
            except Exception as exc:
                responses.append(FileUploadResponse(path=path, error=type(exc).__name__))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                runtime_path = to_runtime_relative_path(self._current_paths().physical_path(path))
                responses.append(FileDownloadResponse(path=path, content=self._sandbox_for_use().files.read(runtime_path)))
            except (GkeRuntimePathError, ValueError):
                responses.append(FileDownloadResponse(path=path, error="invalid_path"))
            except Exception as exc:
                responses.append(FileDownloadResponse(path=path, error=type(exc).__name__))
        return responses

    def read_file(self, path: str) -> bytes:
        return self._read_file(self._current_paths(), path)

    def read_file_for(self, staff_id: str, conversation_id: uuid.UUID, path: str) -> bytes:
        return self._read_file(self._paths(staff_id, str(conversation_id)), path)

    def delete_workspace_for(self, staff_id: str, conversation_id: uuid.UUID) -> None:
        """Remove only one validated conversation directory from the shared pod."""
        paths = self._paths(staff_id, str(conversation_id))
        self._sandbox_for_use().commands.run(f"rm -rf {paths.workspace}", timeout=self._settings.command_timeout_seconds)

    def _read_file(self, paths: ConversationWorkspacePaths, path: str) -> bytes:
        return self._sandbox_for_use().files.read(to_runtime_relative_path(paths.physical_path(path)))

    def _sandbox_for_use(self) -> Any:
        return self._sandbox or GkeSandboxClient(self._settings).get()

    def _current_paths(self) -> ConversationWorkspacePaths:
        configurable = ensure_config().get("configurable") or {}
        staff_id = configurable.get("staff_id")
        conversation_id = configurable.get("thread_id")
        if not isinstance(staff_id, str) or not isinstance(conversation_id, str):
            raise RuntimeError("GKE workspace requires configurable.staff_id and configurable.thread_id")
        return self._paths(staff_id, conversation_id)

    def _paths(self, staff_id: str, conversation_id: str) -> ConversationWorkspacePaths:
        if not _STAFF_ID.fullmatch(staff_id):
            raise RuntimeError("Invalid staff_id for GKE workspace path")
        try:
            normalized_conversation_id = str(uuid.UUID(conversation_id))
        except ValueError as exc:
            raise RuntimeError("Invalid conversation ID for GKE workspace path") from exc
        return ConversationWorkspacePaths(self._settings.workspace_root, staff_id, normalized_conversation_id)
