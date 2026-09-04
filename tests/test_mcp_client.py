"""TLS configuration tests for the MCP HTTP client."""

import ssl
from pathlib import Path

import certifi
import pytest

import mcp_runtime.mcp_client as mcp_client_module
from config.mcp_server_settings import McpServerSettings
from mcp_runtime.mcp_client import McpClient


def test_mcp_client_adds_configured_root_ca_to_system_trust_store(tmp_path) -> None:
    certificate = tmp_path / "company-root.cer"
    certificate.write_bytes(Path(certifi.where()).read_bytes())

    context = McpClient(McpServerSettings(root_ca_path=certificate))._tls_verification_context()

    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_mcp_client_appends_root_ca_to_default_trust_store(monkeypatch, tmp_path) -> None:
    certificate = tmp_path / "company-root.cer"
    certificate.write_text("test certificate", encoding="utf-8")
    loaded_paths: list[str] = []

    class FakeSslContext:
        def load_verify_locations(self, *, cafile: str) -> None:
            loaded_paths.append(cafile)

    monkeypatch.setattr(mcp_client_module.ssl, "create_default_context", lambda: FakeSslContext())

    context = McpClient(McpServerSettings(root_ca_path=certificate))._tls_verification_context()

    assert isinstance(context, FakeSslContext)
    assert loaded_paths == [str(certificate)]


def test_mcp_client_rejects_missing_configured_root_ca(tmp_path) -> None:
    client = McpClient(McpServerSettings(root_ca_path=tmp_path / "missing-root.cer"))

    with pytest.raises(RuntimeError, match="MCP root certificate is missing or empty"):
        client._tls_verification_context()
