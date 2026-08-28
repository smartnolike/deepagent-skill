"""DeepAgents ``BaseSandbox`` adapter for the GKE v1alpha1 Python SDK."""

from __future__ import annotations

import asyncio
from typing import Any

from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox

from sandbox.gke_runtime_paths import GkeRuntimePathError, to_runtime_relative_path


class GkeSandboxBackend(BaseSandbox):
    """Expose one already-created ``k8s_agent_sandbox.Sandbox`` to DeepAgents."""

    def __init__(self, sandbox: Any, default_timeout: int) -> None:
        self._sandbox = sandbox
        self._default_timeout = default_timeout

    @property
    def id(self) -> str:
        return str(getattr(self._sandbox, "claim_name", None) or getattr(self._sandbox, "sandbox_id"))

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        result = self._sandbox.commands.run(command, timeout=timeout or self._default_timeout)
        output = "".join(part for part in (getattr(result, "stdout", ""), getattr(result, "stderr", "")) if part)
        return ExecuteResponse(output=output or "<no output>", exit_code=result.exit_code, truncated=False)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return await asyncio.to_thread(self.execute, command, timeout=timeout)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                runtime_path = to_runtime_relative_path(path)
            except GkeRuntimePathError:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
                continue
            try:
                # k8s-agent-sandbox 0.4.6's Filesystem.write() reduces the
                # path to its basename.  The official Runtime accepts a
                # relative destination as multipart filename, so use its
                # authenticated connector without losing work/output folders.
                self._sandbox.connector.send_request(
                    "POST", "upload", files={"file": (runtime_path, content)}, timeout=60
                )
                responses.append(FileUploadResponse(path=path))
            except Exception as exc:  # SDK exposes provider-specific HTTP errors.
                responses.append(FileUploadResponse(path=path, error=type(exc).__name__))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                runtime_path = to_runtime_relative_path(path)
            except GkeRuntimePathError:
                responses.append(FileDownloadResponse(path=path, error="invalid_path"))
                continue
            try:
                responses.append(FileDownloadResponse(path=path, content=self._sandbox.files.read(runtime_path)))
            except Exception as exc:  # SDK exposes provider-specific HTTP errors.
                responses.append(FileDownloadResponse(path=path, error=type(exc).__name__))
        return responses

    def read_file(self, path: str) -> bytes:
        """Read a canonical workspace path for artifact publication."""
        return self._sandbox.files.read(to_runtime_relative_path(path))
