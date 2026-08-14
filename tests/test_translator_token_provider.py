"""Dynamic model-token provider tests."""

# 30 秒令牌应在同一有效窗口复用，临近过期时才由下一次模型请求触发刷新。

import pytest
from pydantic import SecretStr

from src.agent.translator_token_provider import TranslatorTokenProvider
from src.config.token_auth_settings import TokenAuthSettings


class FakeTokenHttpxClient:
    """按顺序返回 Token 响应，不发起真实 HTTP 请求。"""

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = responses
        self.calls = 0

    async def post_json(
        self, url: str, payload: dict[str, str], timeout_seconds: float
    ) -> dict[str, object]:
        self.calls += 1
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_provider_reuses_short_lived_token_before_refresh_window() -> None:
    client = FakeTokenHttpxClient(
        [{"access_token": "token-one", "expires_in": 30}, {"access_token": "token-two", "expires_in": 30}]
    )
    provider = TranslatorTokenProvider(
        TokenAuthSettings(
            translator_url="https://translator.example/token",
            service_account="svc",
            service_account_password="secret",
            refresh_before_expiry_seconds=5,
        ),
        SecretStr("secret"),
        client,  # type: ignore[arg-type]
    )

    assert await provider.get_token() == "token-one"
    assert await provider.get_token() == "token-one"
    assert client.calls == 1


@pytest.mark.asyncio
async def test_provider_raises_safe_error_for_invalid_response() -> None:
    client = FakeTokenHttpxClient([{"access_token": ""}])
    provider = TranslatorTokenProvider(
        TokenAuthSettings(
            translator_url="https://translator.example/token",
            service_account="svc",
            service_account_password="secret",
        ),
        SecretStr("secret"),
        client,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="MODEL_TOKEN_UNAVAILABLE"):
        await provider.get_token()
