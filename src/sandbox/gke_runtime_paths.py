"""Translate DeepAgent workspace paths to the official Runtime file API paths."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass


class GkeRuntimePathError(ValueError):
    """Raised when a path does not address the conversation workspace."""


def to_runtime_relative_path(path: str) -> str:
    """Return a path relative to Runtime's ``SANDBOX_BASE_DIR=/workspace``.

    The official Agent Sandbox Runtime strips leading slashes before joining a
    request path to ``SANDBOX_BASE_DIR``.  Passing ``/workspace/foo`` directly
    would therefore resolve to ``/workspace/workspace/foo``.  Keep the rest of
    the application on canonical absolute workspace paths and translate only at
    this SDK boundary.
    """
    if not path.startswith("/"):
        raise GkeRuntimePathError("Sandbox file paths must be absolute")

    normalized = posixpath.normpath(path)
    prefixes = {"/workspace/": ""}
    for prefix, replacement in prefixes.items():
        if normalized.startswith(prefix):
            relative = replacement + normalized.removeprefix(prefix)
            if relative and not relative.startswith("../"):
                return relative

    raise GkeRuntimePathError("Path must be inside /workspace")


@dataclass(frozen=True)
class ConversationWorkspacePaths:
    """Map the agent's stable logical paths to one shared Sandbox directory."""

    root: str
    staff_id: str
    conversation_id: str

    @property
    def workspace(self) -> str:
        return f"{self.root.rstrip('/')}/{self.staff_id}/{self.conversation_id}"

    def physical_path(self, path: str) -> str:
        normalized = posixpath.normpath(path)
        aliases = {
            "/work": f"{self.workspace}/work",
            "/output": f"{self.workspace}/output",
            "/workspace/work": f"{self.workspace}/work",
            "/workspace/output": f"{self.workspace}/output",
            "/skill-packages": "/workspace/skill-packages",
            "/workspace/skill-packages": "/workspace/skill-packages",
        }
        for logical, physical in aliases.items():
            if normalized == logical or normalized.startswith(logical + "/"):
                return physical + normalized.removeprefix(logical)
        raise GkeRuntimePathError("Path must be inside /work, /output, or /skill-packages")

    def map_command(self, command: str) -> str:
        """Translate plain and Base64-encoded paths emitted by ``BaseSandbox``."""
        aliases = {
            "/workspace/skill-packages": self.physical_path("/workspace/skill-packages"),
            "/skill-packages": self.physical_path("/skill-packages"),
            "/workspace/output": self.physical_path("/workspace/output"),
            "/output": self.physical_path("/output"),
            "/workspace/work": self.physical_path("/workspace/work"),
            "/work": self.physical_path("/work"),
        }

        # One pass over the original command is essential: a physical output
        # path itself ends in ``/output`` and must never be treated as another
        # logical alias on a later replacement pass.
        path_pattern = re.compile(
            r"(?<![A-Za-z0-9_-])(?P<path>/workspace/(?:skill-packages|output|work)|/(?:skill-packages|output|work))(?=$|/)"
        )
        command = path_pattern.sub(lambda match: aliases[match.group("path")], command)

        def replace_base64(match: re.Match[str]) -> str:
            import base64

            encoded = match.group(2)
            try:
                decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
                mapped = self.physical_path(decoded)
            except (ValueError, UnicodeDecodeError, GkeRuntimePathError):
                return match.group(0)
            return f"{match.group(1)}{base64.b64encode(mapped.encode()).decode()}{match.group(1)}"

        return re.sub(r"(['\"])([A-Za-z0-9+/]{8,}={0,2})\1", replace_base64, command)

    def redact_command_output(self, output: str) -> str:
        """Hide this conversation's physical paths from Agent-visible output.

        A command may print a resolved file name.  Returning that path lets the
        model accidentally feed staff- and conversation-scoped infrastructure
        details back into a file Tool, which intentionally accepts only the
        stable logical workspace paths.  Preserve useful paths as ``/work`` or
        ``/output`` and redact a bare workspace root entirely.
        """
        work = f"{self.workspace}/work"
        output_dir = f"{self.workspace}/output"
        return output.replace(work, "/work").replace(output_dir, "/output").replace(
            self.workspace, "<conversation-workspace>"
        )
