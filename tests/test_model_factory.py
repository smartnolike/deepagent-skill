"""模型 Provider 工厂测试。"""

# 外部 OpenAI 固定 Key 不得触发内部 Translator Token 依赖。

import pytest
from types import SimpleNamespace

from src.agent import model_factory
from src.agent.model_factory import create_chat_model
from src.config.agent_settings import AgentSettings


def test_openai_provider_uses_fixed_api_key() -> None:
    model = create_chat_model(
        AgentSettings(provider="openai", model="gpt-4.1-mini", api_key="test-fixed-key"), None
    )

    assert model.model_name == "gpt-4.1-mini"
    assert model.openai_api_key.get_secret_value() == "test-fixed-key"


def test_openai_provider_requires_fixed_api_key() -> None:
    with pytest.raises(RuntimeError, match="External model requires agent.api_key"):
        create_chat_model(AgentSettings(provider="openai", model="gpt-4.1-mini"), None)


def test_openai_compatible_provider_uses_custom_base_url() -> None:
    model = create_chat_model(
        AgentSettings(
            provider="openai_compatible",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key="deepseek-test-key",
        ),
        None,
    )

    assert str(model.openai_api_base) == "https://api.deepseek.com"


def test_internal_provider_requires_dynamic_token_configuration() -> None:
    with pytest.raises(RuntimeError, match="Internal model requires"):
        create_chat_model(AgentSettings(provider="internal", model="internal-model"), None)


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
            api_key="test-key",
        ),
        SimpleNamespace(async_client=expected_async_client),  # type: ignore[arg-type]
    )

    assert result["http_async_client"] is expected_async_client
