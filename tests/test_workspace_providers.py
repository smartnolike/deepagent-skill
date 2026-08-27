import uuid
from pathlib import Path

from config.sandbox_settings import LocalShellSettings
from sandbox.session_store import WorkspaceReference
from sandbox.workspace_providers import FilesystemWorkspaceProvider, LocalShellWorkspaceProvider


def test_filesystem_provider_uses_skill_root(tmp_path: Path) -> None:
    provider = FilesystemWorkspaceProvider(tmp_path)

    backend = provider.backend()

    assert provider.skills_path == "/"
    assert provider.supports_artifacts is False
    assert backend.cwd == tmp_path


def test_local_provider_creates_reusable_isolated_workspace_and_releases_it(tmp_path: Path) -> None:
    skills = tmp_path / "skill-packages"
    skills.mkdir()
    (skills / "SKILL.md").write_text("instructions")
    workspaces = tmp_path / "workspaces"
    provider = LocalShellWorkspaceProvider(LocalShellSettings(workspace_root=workspaces), skills)
    conversation_id = uuid.uuid4()

    allocation = provider.create(conversation_id)
    reference = WorkspaceReference(uuid.uuid4(), "local_shell", allocation.workspace_reference, None, None)

    assert (Path(allocation.workspace_reference) / "skill-packages" / "SKILL.md").read_text() == "instructions"
    assert (Path(allocation.workspace_reference) / "work").is_dir()
    assert (Path(allocation.workspace_reference) / "output").is_dir()
    assert provider.reusable(reference) is True

    provider.release(reference)

    assert provider.reusable(reference) is False
