"""Workspace backend configuration shared by the DeepAgent harness."""

from typing import Literal

import posixpath

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


class GkeAgentSandboxSettings(BaseModel):
    """One pre-deployed, shared GKE Agent Sandbox."""

    namespace: str
    sandbox_name: str
    connection_mode: Literal["tunnel", "direct"] = "direct"
    router_url: str | None = None
    router_auth_token: SecretStr | None = None
    runtime_port: int = Field(default=38_087, ge=1, le=65_535)
    command_timeout_seconds: int = Field(default=120, ge=1, le=3_600)
    workspace_root: str = "/workspace/staff-workspaces"
    workspace_retention_seconds: int = Field(default=172_800, ge=3_600)

    @field_validator("workspace_root")
    @classmethod
    def validate_workspace_root(cls, value: str) -> str:
        normalized = posixpath.normpath(value)
        if not normalized.startswith("/workspace/"):
            raise ValueError("workspace_root must be a directory below /workspace")
        return normalized


class SandboxSettings(BaseModel):
    """Select the backend that owns one conversation's workspace."""

    provider: Literal["filesystem", "gke_backend"] = "filesystem"
    execute_requires_confirmation: bool = True
    gke: GkeAgentSandboxSettings | None = None

    @model_validator(mode="after")
    def validate_execution_safety(self) -> "SandboxSettings":
        if self.provider == "gke_backend" and self.gke is None:
            raise ValueError("sandbox.gke is required when sandbox.provider is gke_backend")
        if self.provider == "gke_backend" and self.gke and self.gke.connection_mode == "direct" and not self.gke.router_url:
            raise ValueError("sandbox.gke.router_url is required when sandbox.gke.connection_mode is direct")
        return self
