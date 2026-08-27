import uuid
from pathlib import Path

import pytest

from config.sandbox_settings import SandboxSettings
from sandbox.workspace_manager import WorkspaceManager, WorkspaceReference


def test_filesystem_backend_does_not_register_artifacts(tmp_path: Path) -> None:
    manager = WorkspaceManager(SandboxSettings(provider="filesystem"), tmp_path, "postgresql://unused")

    assert manager.skills_path == "/"
    assert manager.supports_artifacts is False


def test_local_artifact_path_maps_to_conversation_output(tmp_path: Path) -> None:
    root = tmp_path / "conversation"
    (root / "output").mkdir(parents=True)
    (root / "output" / "report.xlsx").write_bytes(b"xlsx")
    manager = WorkspaceManager(SandboxSettings(provider="local_shell"), tmp_path, "postgresql://unused")
    reference = WorkspaceReference(uuid.uuid4(), "local_shell", str(root), None, None)

    assert manager.normalize_artifact_path("/output/report.xlsx") == "/workspace/output/report.xlsx"
    assert manager.download_artifact(reference, "/workspace/output/report.xlsx") == b"xlsx"


def test_local_artifact_download_rejects_non_output_path(tmp_path: Path) -> None:
    manager = WorkspaceManager(SandboxSettings(provider="local_shell"), tmp_path, "postgresql://unused")
    reference = WorkspaceReference(uuid.uuid4(), "local_shell", str(tmp_path), None, None)

    with pytest.raises(ValueError, match="/workspace/output"):
        manager.download_artifact(reference, "/workspace/work/private.txt")

    with pytest.raises(ValueError, match="/workspace/output"):
        manager.download_artifact(reference, "/workspace/output/../skill-packages/secret.txt")
