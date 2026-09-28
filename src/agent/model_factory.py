"""OpenAI-compatible LangChain model construction."""

# ChatOpenAI 原生支持 async api_key callback，因而无需修改 OpenAI 协议客户端。

import os
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from collections.abc import Awaitable, Callable

from agent.translator_token_provider import TranslatorTokenProvider
from common.httpx_client import HttpxClient
from config.agent_settings import AgentSettings
from core.runtime_secrets import RuntimeSecrets


def create_chat_model(
    settings: AgentSettings,
    httpx_client: HttpxClient | None,
    runtime_secrets: RuntimeSecrets | None = None,
    translator_token_provider: TranslatorTokenProvider | None = None,
) -> ChatOpenAI | ChatGoogleGenerativeAI:
    """按 provider 创建内部、OpenAI-compatible 或 Google GenAI 模型。"""
    if settings.provider == "google_genai":
        client_args: dict[str, str] = {}
        if os.getenv("AGENT_ENV") == "local":
            client_args["proxy"] = "http://10.98.40.131:3128"
        return ChatGoogleGenerativeAI(
            model=settings.model,
            project="hsbc-9445955-wselevuk01-dev",
            location="eu",
            vertexai=True,
            retries=1,
            request_timeout=300,
            client_args=client_args,
        )

    api_key: str | Callable[[], Awaitable[str]]
    base_url: str | None
    if settings.provider == "internal":
        if settings.token_auth is None or settings.base_url is None:
            raise RuntimeError("Internal model requires agent.base_url and agent.token_auth")
        if httpx_client is None:
            raise RuntimeError("HTTP client is required for dynamic model token authentication")
        if runtime_secrets is None:
            raise RuntimeError("Internal model requires resolved runtime secrets")
        provider = translator_token_provider or TranslatorTokenProvider(
            settings.token_auth,
            runtime_secrets.require_translator_service_account_password(),
            httpx_client,
        )
        api_key = provider.get_token
        base_url = settings.base_url
    else:
        if settings.api_key is None:
            raise RuntimeError("External model requires agent.api_key")
        api_key = settings.api_key.get_secret_value()
        base_url = settings.base_url if settings.provider == "openai_compatible" else None

    return ChatOpenAI(
        model=settings.model,
        api_key=api_key,
        base_url= base_url,
        streaming=True,
        max_retries= 1,
        http_async_client=httpx_client.async_client
    )
