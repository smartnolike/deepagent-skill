"""OpenAI-compatible LangChain model construction."""

# ChatOpenAI 原生支持 async api_key callback，因而无需修改 OpenAI 协议客户端。

from langchain_openai import ChatOpenAI
from collections.abc import Awaitable, Callable

from agent.translator_token_provider import TranslatorTokenProvider
from common.httpx_client import HttpxClient
from config.agent_settings import AgentSettings
from core.runtime_secrets import RuntimeSecrets


def create_chat_model(
    settings: AgentSettings, httpx_client: HttpxClient | None, runtime_secrets: RuntimeSecrets | None = None
) -> ChatOpenAI:
    """按 provider 创建内部动态 Token 或外部 OpenAI-compatible 固定 Key 模型。"""
    api_key: str | Callable[[], Awaitable[str]]
    base_url: str | None
    if settings.provider == "internal":
        if settings.token_auth is None or settings.base_url is None:
            raise RuntimeError("Internal model requires agent.base_url and agent.token_auth")
        if httpx_client is None:
            raise RuntimeError("HTTP client is required for dynamic model token authentication")
        if runtime_secrets is None:
            raise RuntimeError("Internal model requires resolved runtime secrets")
        api_key = TranslatorTokenProvider(
            settings.token_auth,
            runtime_secrets.require_translator_service_account_password(),
            httpx_client,
        ).get_token
        base_url = settings.base_url
    else:
        if settings.api_key is None:
            raise RuntimeError("External model requires agent.api_key")
        api_key = settings.api_key.get_secret_value()
        base_url = settings.base_url if settings.provider == "openai_compatible" else None

    model_name = (settings.model or "").removeprefix("openai:")
    model_options: dict[str, object] = {
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "streaming": True,
        "max_retries": 1,
    }
    if httpx_client is not None:
        # 内部模型网关同样通过企业根证书访问，不能只让 Translator 使用该证书。
        model_options["http_async_client"] = httpx_client.async_client
    return ChatOpenAI(**model_options)
