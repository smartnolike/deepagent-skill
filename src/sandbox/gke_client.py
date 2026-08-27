"""Thin compatibility boundary around the pinned GKE Agent Sandbox SDK."""

from __future__ import annotations

import uuid
from typing import Any

from config.sandbox_settings import GkeAgentSandboxSettings


class GkeSandboxClient:
    """Create, reconnect, and terminate v1alpha1 GKE Agent Sandboxes."""

    def __init__(self, settings: GkeAgentSandboxSettings) -> None:
        self._settings = settings

    def create(self, conversation_id: uuid.UUID) -> Any:
        return self._client().create_sandbox(
            template=self._settings.template_name,
            namespace=self._settings.namespace,
            sandbox_ready_timeout=self._settings.startup_timeout_seconds,
            labels={"deepagent-conversation-id": str(conversation_id)},
            shutdown_after_seconds=self._settings.absolute_ttl_seconds,
        )

    def get(self, claim_name: str, namespace: str | None) -> Any:
        sandbox = self._client().get_sandbox(claim_name, namespace or self._settings.namespace)
        token = self._settings.router_auth_token.get_secret_value() if self._settings.router_auth_token else ""
        if token:
            sandbox.connector.session.headers["Authorization"] = f"Bearer {token}"
        return sandbox

    def terminate(self, claim_name: str, namespace: str | None) -> None:
        self.get(claim_name, namespace).terminate()

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
