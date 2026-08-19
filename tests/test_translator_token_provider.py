"""Dynamic model-token provider tests."""

# 30 秒令牌应在同一有效窗口复用，临近过期时才由下一次模型请求触发刷新。

import pytest
from pydantic import SecretStr

from agent.translator_token_provider import TranslatorTokenProvider
from config.token_auth_settings import TokenAuthSettings


class FakeTokenHttpxClient:
    """按顺序返回 Token 响应，不发起真实 HTTP 请求。"""

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = responses
        self.calls = 0
        self.payloads: list[dict[str, object]] = []

    async def post_json(
        self, url: str, payload: dict[str, object], timeout_seconds: float
    ) -> dict[str, object]:
        self.calls += 1
        self.payloads.append(payload)
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_provider_reuses_short_lived_token_before_refresh_window() -> None:
    client = FakeTokenHttpxClient(
        [{"issued_token": "token-one"}, {"issued_token": "token-two"}]
    )
    provider = TranslatorTokenProvider(
        TokenAuthSettings(
            translator_url="https://translator.example/token",
            service_account_name="svc",
            service_account_password="secret",
            refresh_before_expiry_seconds=5,
        ),
        SecretStr("secret"),
        client,  # type: ignore[arg-type]
    )

    assert await provider.get_token() == "token-one"
    assert await provider.get_token() == "token-one"
    assert client.calls == 1
    assert client.payloads == [
        {
            "input_token_state": {
                "token_type": "CREDENTIAL",
                "username": "svc",
                "password": "secret",
            },
            "output_token_state": {"token_type": "JWT"},
        }
    ]


@pytest.mark.asyncio
async def test_provider_raises_safe_error_for_invalid_response() -> None:
    client = FakeTokenHttpxClient([{"issued_token": ""}])
    provider = TranslatorTokenProvider(
        TokenAuthSettings(
            translator_url="https://translator.example/token",
            service_account_name="svc",
            service_account_password="secret",
        ),
        SecretStr("secret"),
        client,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="MODEL_TOKEN_UNAVAILABLE"):
        await provider.get_token()


def test_provider_requires_refresh_window_shorter_than_documented_ttl() -> None:
    """避免每次模型请求都因安全窗口覆盖整个 Token 生命周期而刷新。"""
    with pytest.raises(ValueError, match="refresh_before_expiry_seconds"):
        TokenAuthSettings(
            translator_url="https://translator.example/token",
            service_account_name="svc",
            service_account_password="secret",
            token_ttl_seconds=30,
            refresh_before_expiry_seconds=30,
        )
