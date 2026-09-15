"""Thin compatibility boundary around the pinned GKE Agent Sandbox SDK."""

from __future__ import annotations

from typing import Any

from config.sandbox_settings import GkeAgentSandboxSettings


class GkeSandboxClient:
    """Connect through the Router to one pre-deployed SandboxClaim."""

    def __init__(self, settings: GkeAgentSandboxSettings) -> None:
        self._settings = settings

    def get(self) -> Any:
        sandbox = self._client().get_sandbox(self._settings.sandbox_claim_name, self._settings.namespace)
        token = self._settings.router_auth_token.get_secret_value() if self._settings.router_auth_token else ""
        if token:
            sandbox.connector.session.headers["Authorization"] = f"Bearer {token}"
        return sandbox

    def _client(self):
        from k8s_agent_sandbox import SandboxClient
        from k8s_agent_sandbox.models import (
            SandboxDirectConnectionConfig,
            SandboxLocalTunnelConnectionConfig,
        )

        if self._settings.connection_mode == "tunnel":
            connection = SandboxLocalTunnelConnectionConfig(server_port=self._settings.runtime_port)
        else:
            connection = SandboxDirectConnectionConfig(
                api_url=self._settings.router_url, server_port=self._settings.runtime_port
            )
        return SandboxClient(connection_config=connection)
