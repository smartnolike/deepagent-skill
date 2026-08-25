"""Create the DeepAgents backend selected by typed sandbox settings."""

from pathlib import Path
import sys

from deepagents.backends import FilesystemBackend, LocalShellBackend
from langchain_kubernetes import KubernetesProviderConfig, KubernetesSandboxManager

from config.sandbox_settings import SandboxSettings


def create_sandbox_backend(settings: SandboxSettings, skills_root: Path):
    """Return a backend rooted at the installed Skill packages.

    ``LocalShellBackend`` is intentionally limited to an explicitly enabled
    development configuration. It executes on the host and is never a GKE
    fallback. GKE Agent Sandbox is created by :func:`create_gke_sandbox_manager`.
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

    raise RuntimeError("gke_agent backends must be created through KubernetesSandboxManager")


def create_gke_sandbox_manager(settings: SandboxSettings) -> KubernetesSandboxManager:
    """Build the packaged DeepAgents/GKE integration for one application process.

    ``langchain-kubernetes`` owns the DeepAgents sandbox protocol and uses the
    official ``k8s-agent-sandbox`` client to claim warm-pool sandboxes and route
    command traffic through the configured in-cluster Sandbox Router.
    """
    if settings.provider != "gke_agent" or settings.gke is None:
        raise ValueError("create_gke_sandbox_manager requires sandbox.provider=gke_agent")

    gke = settings.gke
    provider_config = {
        "mode": "agent-sandbox",
        "namespace": gke.namespace,
        "template_name": gke.template_name,
        "warm_pool_name": gke.warm_pool_name,
        "connection_mode": gke.connection_mode,
        "server_port": gke.runtime_port,
        "startup_timeout_seconds": gke.startup_timeout_seconds,
        "default_exec_timeout": gke.command_timeout_seconds,
    }
    if gke.router_url is not None:
        provider_config["api_url"] = gke.router_url
    return KubernetesSandboxManager(
        KubernetesProviderConfig(**provider_config),
        ttl_idle_seconds=gke.idle_ttl_seconds,
        default_labels={"application": "deepagent-platform"},
    )
