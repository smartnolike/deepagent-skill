"""Short-lived translator token provider for OpenAI-compatible models."""

# Token 仅在新模型 HTTP 请求建立前按需获取；不会在已建立的 SSE 流中刷新。

import asyncio
import logging

from pydantic import SecretStr

from src.common.httpx_client import HttpxClient
from src.config.token_auth_settings import TokenAuthSettings

logger = logging.getLogger(__name__)


class TranslatorTokenProvider:
    """Fetch and cache a translator-issued bearer token for its documented lifetime."""

    def __init__(self, settings: TokenAuthSettings, service_account_password: SecretStr, httpx_client: HttpxClient) -> None:
        self._settings = settings
        self._service_account_password = service_account_password
        self._httpx_client = httpx_client
        self._token: str | None = None
        self._expires_at: float = 0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Return a valid token before an OpenAI-compatible request is opened."""
        if self._is_usable():
            return self._token_or_raise()
        async with self._lock:
            if self._is_usable():
                return self._token_or_raise()
            return await self._refresh()

    def _is_usable(self) -> bool:
        """Check the cache with a monotonic clock and configured safety window."""
        now = asyncio.get_running_loop().time()
        return self._token is not None and now < self._expires_at - self._settings.refresh_before_expiry_seconds

    def _token_or_raise(self) -> str:
        """Narrow an internally checked optional cached token to a string."""
        if self._token is None:
            raise RuntimeError("MODEL_TOKEN_UNAVAILABLE")
        return self._token

    async def _refresh(self) -> str:
        """Request a new credential without logging credentials or response content."""
        try:
            response = await self._httpx_client.post_json(
                self._settings.translator_url,
                {
                    "input_token_state": {
                        "token_type": "CREDENTIAL",
                        "username": self._settings.service_account_name,
                        "password": self._service_account_password.get_secret_value(),
                    },
                    "output_token_state": {"token_type": "JWT"},
                },
                self._settings.request_timeout_seconds,
            )
            token = response.get(self._settings.token_field)
            if not isinstance(token, str) or not token:
                raise ValueError("token response does not contain a non-empty token")
        except Exception as exc:
            logger.warning("model_token_refresh_failed error_type=%s", type(exc).__name__)
            raise RuntimeError("MODEL_TOKEN_UNAVAILABLE") from exc

        self._token = token
        self._expires_at = asyncio.get_running_loop().time() + self._settings.token_ttl_seconds
        logger.info("model_token_refreshed token_ttl_seconds=%s", self._settings.token_ttl_seconds)
        return token
