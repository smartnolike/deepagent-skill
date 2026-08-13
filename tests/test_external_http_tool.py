"""外部 HTTP 自定义 Tool 测试。"""

# 测试使用 certifi 的有效 CA 文件和 MockTransport，不访问真实网络。

import shutil

import certifi
import httpx

from src.core.http_client import ExternalHttpClient
from src.tools.external_status import get_configured_service_status


async def test_external_status_tool_uses_custom_ca_and_mock_transport(tmp_path) -> None:
    certificate = tmp_path / "root.cer"
    shutil.copyfile(certifi.where(), certificate)
    client = ExternalHttpClient(
        certificate,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"status": "ok"})),
    )
    try:
        assert await get_configured_service_status(client, "https://service.example/status") == '{"status": "ok"}'
    finally:
        await client.close()


def test_external_http_client_rejects_empty_certificate(tmp_path) -> None:
    certificate = tmp_path / "root.cer"
    certificate.touch()
    try:
        ExternalHttpClient(certificate)
    except RuntimeError as error:
        assert "missing or empty" in str(error)
    else:
        raise AssertionError("Empty root certificate must be rejected")
