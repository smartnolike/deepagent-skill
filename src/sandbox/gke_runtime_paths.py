"""Translate DeepAgent workspace paths to the official Runtime file API paths."""

from __future__ import annotations

import posixpath


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
    prefixes = {
        "/workspace/": "",
        "/skill-packages/": "skill-packages/",
        "/work/": "work/",
        "/output/": "output/",
    }
    for prefix, replacement in prefixes.items():
        if normalized.startswith(prefix):
            relative = replacement + normalized.removeprefix(prefix)
            if relative and not relative.startswith("../"):
                return relative

    raise GkeRuntimePathError("Path must be inside /workspace, /skill-packages, /work, or /output")
