"""模型 Provider 工厂测试。"""

# 外部 OpenAI 固定 Key 不得触发内部 Translator Token 依赖。

import pytest
from types import SimpleNamespace

from agent import model_factory
from agent.model_factory import create_chat_model
from config.agent_settings import AgentSettings
from test_values import TEST_API_KEY


def test_openai_provider_uses_fixed_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    expected_async_client = object()

    def chat_openai_probe(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(model_factory, "ChatOpenAI", chat_openai_probe)
    model = create_chat_model(
        AgentSettings(provider="openai", model="gpt-4.1-mini", api_key=TEST_API_KEY),
        SimpleNamespace(async_client=expected_async_client),  # type: ignore[arg-type]
    )

    assert model["model"] == "gpt-4.1-mini"
    assert model["api_key"] == TEST_API_KEY
    assert model["http_async_client"] is expected_async_client


def test_openai_provider_requires_fixed_api_key() -> None:
    with pytest.raises(RuntimeError, match="External model requires agent.api_key"):
        create_chat_model(
            AgentSettings(provider="openai", model="gpt-4.1-mini"),
            SimpleNamespace(async_client=object()),  # type: ignore[arg-type]
        )


def test_openai_compatible_provider_uses_custom_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def chat_openai_probe(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(model_factory, "ChatOpenAI", chat_openai_probe)
    model = create_chat_model(
        AgentSettings(
            provider="openai_compatible",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key=TEST_API_KEY,
        ),
        SimpleNamespace(async_client=object()),  # type: ignore[arg-type]
    )

    assert model["base_url"] == "https://api.deepseek.com"


def test_internal_provider_requires_dynamic_token_configuration() -> None:
    with pytest.raises(RuntimeError, match="Internal model requires"):
        create_chat_model(AgentSettings(provider="internal", model="internal-model"), None)


def test_google_genai_provider_uses_vertex_ai_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def chat_google_probe(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(model_factory, "ChatGoogleGenerativeAI", chat_google_probe)
    result = model_factory.create_chat_model(
        AgentSettings(provider="google_genai", model="gemini-2.5-pro"), None
    )

    assert result["model"] == "gemini-2.5-pro"
    assert result["project"] == "hsbc-9445955-wselevuk01-dev"
    assert result["location"] == "eu"
    assert result["vertexai"] is True


def test_openai_compatible_provider_passes_application_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型网关请求必须复用应用持有的、配置企业根证书的异步客户端。"""
    captured: dict[str, object] = {}
    expected_async_client = object()

    def chat_openai_probe(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(model_factory, "ChatOpenAI", chat_openai_probe)
    result = model_factory.create_chat_model(
        AgentSettings(
            provider="openai_compatible",
            model="compatible-model",
            base_url="https://model.example/v1",
            api_key=TEST_API_KEY,
        ),
        SimpleNamespace(async_client=expected_async_client),  # type: ignore[arg-type]
    )

    assert result["http_async_client"] is expected_async_client
