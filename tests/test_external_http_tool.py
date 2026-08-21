"""外部 HTTP 自定义 Tool 测试。"""

# 测试使用 certifi 的有效 CA 文件和 MockTransport，不访问真实网络。

import shutil

import certifi
import httpx

from common.httpx_client import HttpxClient
from config.tool_settings import PROJECT_ROOT, ToolSettings
from langgraph.store.memory import InMemoryStore
from tools.danaan_json_schema import get_danaan_json_schema
from tools.registry import CustomToolRegistry
from services.memory_service import MemoryService


async def test_danaan_json_schema_tool_gets_one_resource_version_from_allowlisted_base_url(tmp_path) -> None:
    certificate = tmp_path / "root.cer"
    shutil.copyfile(certifi.where(), certificate)
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        assert request.method == "GET"
        return httpx.Response(200, json={"code": 200, "data": {"schema": {"type": "object"}}})

    client = HttpxClient(
        certificate,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await get_danaan_json_schema(
            client,
            "https://danaan.example/api/terraform/schemas",
            "cloudsql522",
        )
        assert result == '{"code": 200, "data": {"schema": {"type": "object"}}}'
        assert requested_paths == ["/api/terraform/schemas/cloudsql522"]
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


async def test_registry_exposes_danaan_json_schema_with_camel_case_resource_version(tmp_path) -> None:
    certificate = tmp_path / "root.cer"
    shutil.copyfile(certifi.where(), certificate)
    client = HttpxClient(certificate, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    try:
        tools = CustomToolRegistry(
            ToolSettings(danaan_json_schema_url="https://danaan.example/api/terraform/schemas"),
            client,
            None,
            MemoryService(InMemoryStore()),
        ).build()
        schema_tool = next(tool for tool in tools if tool.name == "danaan_json_schema")
        assert "resourceVersion" in schema_tool.args_schema.model_json_schema()["properties"]
        assert "echo_text" not in {tool.name for tool in tools}
    finally:
        await client.close()
