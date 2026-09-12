"""MCP credential-header resolution tests."""

import pytest
from pydantic import SecretStr

from config.settings import Settings
from core.runtime_secrets import RuntimeSecrets
from mcp_runtime.mcp_header_resolver import McpHeaderResolver


class FakeTranslatorTokenProvider:
    """Return a distinct DSP token on each explicit resolver refresh."""

    def __init__(self) -> None:
        self.calls = 0

    async def get_token(self) -> str:
        self.calls += 1
        return f"dsp-{self.calls}"


def _settings(*, refresh_on_reconnect: bool = False) -> Settings:
    return Settings.model_validate(
        {
            "agent_env": "local",
            "allow_test_doubles": True,
            "database": {"host": "localhost", "name": "deepagent", "user": "postgres", "password": "postgres"},
            "api_auth_token": "test-token",
            "mcp_servers": {
                "confidence": {
                    "transport": "http",
                    "url": "https://mcp.example.internal/api",
                    "headers": {"X-Token-Type": "dsp"},
                    "credential_headers": {
                        "X-DSP": {
                            "source": "translator_dsp",
                            "prefix": "Bearer ",
                            "refresh_on_reconnect": refresh_on_reconnect,
                        },
                        "X-PAT": {
                            "source": "gcp_secret_manager",
                            "secret_version": "projects/example/secrets/confidence-pat/versions/1",
                        },
                    },
                    "tools": ["search"],
                }
            },
        }
    )


@pytest.mark.asyncio
async def test_mcp_headers_cache_startup_secrets_and_dsp_by_default() -> None:
    """Default reconnects reuse both the startup PAT and the first DSP token."""
    provider = FakeTranslatorTokenProvider()
    resolver = McpHeaderResolver(
        _settings(),
        RuntimeSecrets(
            mcp_secrets={"projects/example/secrets/confidence-pat/versions/1": SecretStr("pat-value")}
        ),
        provider,  # type: ignore[arg-type]
    )

    initial = await resolver.resolve("confidence", reconnect=False)
    reconnected = await resolver.resolve("confidence", reconnect=True)

    assert initial == {"X-Token-Type": "dsp", "X-DSP": "Bearer dsp-1", "X-PAT": "pat-value"}
    assert reconnected == initial
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_mcp_headers_refresh_only_opted_in_dsp_on_reconnect() -> None:
    """A reconnect refreshes DSP when requested but retains the startup PAT."""
    provider = FakeTranslatorTokenProvider()
    resolver = McpHeaderResolver(
        _settings(refresh_on_reconnect=True),
        RuntimeSecrets(
            mcp_secrets={"projects/example/secrets/confidence-pat/versions/1": SecretStr("pat-value")}
        ),
        provider,  # type: ignore[arg-type]
    )

    initial = await resolver.resolve("confidence", reconnect=False)
    reconnected = await resolver.resolve("confidence", reconnect=True)

    assert initial["X-DSP"] == "Bearer dsp-1"
    assert reconnected["X-DSP"] == "Bearer dsp-2"
    assert initial["X-PAT"] == reconnected["X-PAT"] == "pat-value"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_mcp_headers_refresh_dsp_for_tool_request_but_not_pat() -> None:
    """A Tool request receives a current DSP header while reusing the PAT."""
    provider = FakeTranslatorTokenProvider()
    resolver = McpHeaderResolver(
        _settings(),
        RuntimeSecrets(
            mcp_secrets={"projects/example/secrets/confidence-pat/versions/1": SecretStr("pat-value")}
        ),
        provider,  # type: ignore[arg-type]
    )

    initial = await resolver.resolve("confidence", reconnect=False)
    refreshed = await resolver.resolve("confidence", reconnect=False, refresh_dsp=True)

    assert initial["X-DSP"] == "Bearer dsp-1"
    assert refreshed["X-DSP"] == "Bearer dsp-2"
    assert refreshed["X-PAT"] == "pat-value"
    assert provider.calls == 2
