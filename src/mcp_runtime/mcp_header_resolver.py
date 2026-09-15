"""Resolve sensitive MCP headers from startup secrets and the translator token provider."""

from agent.translator_token_provider import TranslatorTokenProvider
from config.settings import Settings
from core.runtime_secrets import RuntimeSecrets


class McpHeaderResolver:
    """Build connection headers without storing secrets in settings or logs.

    Secret Manager values are startup-resolved in ``RuntimeSecrets``. DSP values
    are cached after first use and can be refreshed only for reconnects that
    explicitly opt in through ``refresh_on_reconnect``.
    """

    def __init__(
        self,
        settings: Settings,
        runtime_secrets: RuntimeSecrets,
        translator_token_provider: TranslatorTokenProvider | None = None,
    ) -> None:
        self._settings = settings
        self._runtime_secrets = runtime_secrets
        self._translator_token_provider = translator_token_provider
        self._dsp_headers: dict[str, str] = {}

    async def resolve(self, server_id: str, *, reconnect: bool, refresh_dsp: bool = False) -> dict[str, str]:
        """Return MCP headers, refreshing short-lived DSP credentials when requested."""
        server = self._settings.mcp_servers[server_id]
        headers = dict(server.headers)
        for header_name, credential in server.credential_headers.items():
            if credential.source == "gcp_secret_manager":
                assert credential.secret_version is not None  # validated by settings
                headers[header_name] = credential.prefix + self._runtime_secrets.require_mcp_secret(
                    credential.secret_version
                ).get_secret_value()
                continue

            cached = self._dsp_headers.get(header_name)
            if cached is None or refresh_dsp or (reconnect and credential.refresh_on_reconnect):
                if self._translator_token_provider is None:
                    raise RuntimeError("MCP DSP token provider is unavailable")
                cached = await self._translator_token_provider.get_token()
                self._dsp_headers[header_name] = cached
            headers[header_name] = credential.prefix + cached
        return headers
