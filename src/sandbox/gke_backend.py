"""DeepAgents adapter for one shared, pre-deployed GKE Sandbox."""

from __future__ import annotations

import asyncio
import base64
import re
import shlex
import uuid
from datetime import UTC, datetime
from typing import Any

from deepagents.backends.protocol import ExecuteResponse, FileData, FileDownloadResponse, FileUploadResponse, LsResult, ReadResult
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.utils import _get_backend_read_file_type, check_empty_content, slice_read_response
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
        return self._settings.sandbox_claim_name

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        paths = self._current_paths()
        mapped = paths.map_command(command)
        prefix = (
            f"mkdir -p {paths.workspace}/work {paths.workspace}/output && "
            f"cd {paths.workspace}/work && export DEEPAGENT_WORKSPACE={paths.workspace}"
        )
        # The official Python Runtime uses ``shlex.split`` and invokes the
        # resulting argv directly.  It does not interpret ``&&`` or ``cd``
        # unless we explicitly start a shell.  ``mapped`` is the original
        # Agent command (aside from workspace path aliases); this wrapper does
        # not generate or alter its script content.
        shell_command = f"{prefix} && {mapped}"
        result = self._sandbox_for_use().commands.run(
            f"sh -c {shlex.quote(shell_command)}", timeout=timeout or self._settings.command_timeout_seconds
        )
        output = "".join(part for part in (getattr(result, "stdout", ""), getattr(result, "stderr", "")) if part)
        return ExecuteResponse(output=paths.redact_command_output(output) or "<no output>", exit_code=result.exit_code, truncated=False)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return await asyncio.to_thread(self.execute, command, timeout=timeout)

    def ls(self, path: str) -> LsResult:
        """List files through the Runtime file API instead of shelling out.

        ``BaseSandbox.ls`` runs a generated ``python3 -c`` command and silently
        discards its stderr.  That makes a Runtime command transport failure
        indistinguishable from an empty Skill directory.  The GKE SDK already
        exposes the Runtime's structured list endpoint, so use it directly.
        """
        try:
            physical_path = self._current_paths().physical_path(path)
            runtime_path = to_runtime_relative_path(physical_path)
            entries = self._sandbox_for_use().files.list(runtime_path)
        except (GkeRuntimePathError, ValueError) as exc:
            return LsResult(error=f"Path '{path}': invalid_path ({exc})", entries=None)
        except Exception as exc:
            return LsResult(error=f"Cannot list '{path}': {type(exc).__name__}: {exc}", entries=None)

        logical_root = path.rstrip("/") or "/"
        results = []
        for entry in entries:
            is_dir = getattr(entry, "type", None) == "directory"
            entry_path = f"{logical_root}/{entry.name}"
            if is_dir:
                entry_path += "/"
            results.append(
                {
                    "path": entry_path,
                    "is_dir": is_dir,
                    "size": getattr(entry, "size", 0),
                    "modified_at": datetime.fromtimestamp(getattr(entry, "mod_time", 0), tz=UTC).isoformat(),
                }
            )
        results.sort(key=lambda item: item["path"])
        return LsResult(entries=results)

    async def als(self, path: str) -> LsResult:
        return await asyncio.to_thread(self.ls, path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        """Read through the Runtime file API instead of BaseSandbox's shell command."""
        if limit <= 0:
            return ReadResult(file_data=FileData(content="", encoding="utf-8"), no_lines_requested=True)
        try:
            physical_path = self._current_paths().physical_path(file_path)
            raw = self._sandbox_for_use().files.read(to_runtime_relative_path(physical_path))
        except (GkeRuntimePathError, ValueError) as exc:
            return ReadResult(error=f"File '{file_path}': invalid_path ({exc})")
        except Exception as exc:
            return ReadResult(error=f"File '{file_path}': {type(exc).__name__}: {exc}")

        if _get_backend_read_file_type(file_path) != "text":
            return ReadResult(file_data=FileData(content=base64.standard_b64encode(raw).decode("ascii"), encoding="base64"))
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            return ReadResult(file_data=FileData(content=base64.standard_b64encode(raw).decode("ascii"), encoding="base64"))

        empty_message = check_empty_content(content)
        if empty_message:
            return ReadResult(file_data=FileData(content=empty_message, encoding="utf-8"))
        return slice_read_response(FileData(content=content, encoding="utf-8"), offset, limit)

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        return await asyncio.to_thread(self.read, file_path, offset, limit)

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
