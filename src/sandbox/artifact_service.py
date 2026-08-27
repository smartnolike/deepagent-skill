"""Provider-neutral output-path validation and artifact file reads."""

from __future__ import annotations

import posixpath
from typing import Protocol

from sandbox.session_store import WorkspaceReference


class OutputReader(Protocol):
    def read_output(self, reference: WorkspaceReference, path: str) -> bytes: ...


class WorkspaceArtifactService:
    """Restrict published files to the conversation workspace output directory."""

    @staticmethod
    def normalize_path(path: str) -> str:
        if path.startswith("/output/"):
            path = f"/workspace{path}"
        return posixpath.normpath(path)

    def read(self, reference: WorkspaceReference, provider: OutputReader, path: str) -> bytes:
        normalized = self.normalize_path(path)
        if not normalized.startswith("/workspace/output/"):
            raise ValueError("Artifacts must be published from /workspace/output")
        return provider.read_output(reference, normalized)
