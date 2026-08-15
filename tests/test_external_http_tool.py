"""外部 HTTP 自定义 Tool 测试。"""

# 测试使用 certifi 的有效 CA 文件和 MockTransport，不访问真实网络。

import shutil

import certifi
import httpx

from src.common.httpx_client import HttpxClient
from src.config.tool_settings import PROJECT_ROOT, ToolSettings
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


def test_relative_root_ca_path_is_resolved_from_project_root(monkeypatch, tmp_path) -> None:
    """证书相对路径不应受 PyCharm 或命令行的当前工作目录影响。"""
    monkeypatch.chdir(tmp_path)

    settings = ToolSettings()

    assert settings.root_ca_path == (PROJECT_ROOT / "build/root.cer").resolve()


def test_absolute_root_ca_path_is_preserved(tmp_path) -> None:
    """部署环境显式提供的绝对证书路径必须保持不变。"""
    certificate = (tmp_path / "company-root.cer").resolve()

    settings = ToolSettings(root_ca_path=certificate)

    assert settings.root_ca_path == certificate
