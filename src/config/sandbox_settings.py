"""Workspace backend configuration shared by the DeepAgent harness."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator


class LocalShellSettings(BaseModel):
    """Development-only host workspace settings."""

    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_output_bytes: int = Field(default=20_000, ge=1_024, le=1_000_000)
    workspace_root: Path = Path(".runtime/deepagent-workspaces")


class GkeAgentSandboxSettings(BaseModel):
    """Settings for the official GKE Agent Sandbox Python client."""

    namespace: str
    template_name: str
    connection_mode: Literal["tunnel", "direct"] = "direct"
    router_url: str | None = None
    router_auth_token: SecretStr | None = None
    runtime_port: int = Field(default=38_087, ge=1, le=65_535)
    startup_timeout_seconds: int = Field(default=120, ge=1, le=600)
    command_timeout_seconds: int = Field(default=120, ge=1, le=3_600)
    idle_ttl_seconds: int = Field(default=1_800, ge=60)
    absolute_ttl_seconds: int = Field(default=7_200, ge=60)


class SandboxSettings(BaseModel):
    """Select the backend that owns one conversation's workspace."""

    provider: Literal["filesystem", "local_shell", "gke_backend"] = "filesystem"
    execute_requires_confirmation: bool = True
    local_shell: LocalShellSettings = Field(default_factory=LocalShellSettings)
    gke: GkeAgentSandboxSettings | None = None

    @model_validator(mode="after")
    def validate_execution_safety(self) -> "SandboxSettings":
        if self.provider == "local_shell" and not self.execute_requires_confirmation:
            raise ValueError("local_shell requires execute_requires_confirmation")
        if self.provider == "gke_backend" and self.gke is None:
            raise ValueError("sandbox.gke is required when sandbox.provider is gke_backend")
        if self.provider == "gke_backend" and self.gke and self.gke.connection_mode == "direct" and not self.gke.router_url:
            raise ValueError("sandbox.gke.router_url is required when sandbox.gke.connection_mode is direct")
        return self
