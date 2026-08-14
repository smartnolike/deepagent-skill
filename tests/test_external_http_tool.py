"""外部 HTTP 自定义 Tool 测试。"""

# 测试使用 certifi 的有效 CA 文件和 MockTransport，不访问真实网络。

import shutil

import certifi
import httpx

from src.common.httpx_client import HttpxClient
from src.tools.echo import echo_text
from src.tools.external_status import get_configured_service_status


async def test_external_status_tool_uses_custom_ca_and_mock_transport(tmp_path) -> None:
    certificate = tmp_path / "root.cer"
    shutil.copyfile(certifi.where(), certificate)
    client = HttpxClient(
        certificate,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"status": "ok"})),
    )
    try:
        assert await get_configured_service_status(client, "https://service.example/status") == '{"status": "ok"}'
    finally:
        await client.close()


def test_httpx_client_rejects_empty_certificate(tmp_path) -> None:
    certificate = tmp_path / "root.cer"
    certificate.touch()
    try:
        HttpxClient(certificate)
    except RuntimeError as error:
        assert "missing or empty" in str(error)
    else:
        raise AssertionError("Empty root certificate must be rejected")


async def test_echo_text_tool_returns_its_input() -> None:
    assert await echo_text.ainvoke({"text": "你好，DeepAgent"}) == "你好，DeepAgent"
