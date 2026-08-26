"""Create the DeepAgents backend selected by typed sandbox settings."""

from pathlib import Path
import sys

from deepagents.backends import FilesystemBackend, LocalShellBackend

from config.sandbox_settings import SandboxSettings


def create_sandbox_backend(settings: SandboxSettings, skills_root: Path):
    """Return a backend rooted at the installed Skill packages.

    ``LocalShellBackend`` is intentionally limited to an explicitly enabled
    development configuration. GKE execution is exposed only by the dedicated
    Skill runner tool, never as the Agent's filesystem backend.
    """
    if settings.provider == "filesystem":
        return FilesystemBackend(root_dir=skills_root)

    if settings.provider == "local_shell":
        if not settings.allow_agent_shell:
            return FilesystemBackend(root_dir=skills_root)
        return LocalShellBackend(
            root_dir=skills_root,
            virtual_mode=True,
            timeout=settings.local_shell.timeout_seconds,
            max_output_bytes=settings.local_shell.max_output_bytes,
            inherit_env=False,
            env={
                # Make the project's virtualenv Python available to Skill scripts
                # without inheriting cloud credentials and other host variables.
                "PATH": f"{Path(sys.executable).parent}:/usr/local/bin:/usr/bin:/bin",
                "HOME": str(skills_root),
            },
        )

    # Keep Skill inspection local when the script runner targets GKE.
    return FilesystemBackend(root_dir=skills_root)
