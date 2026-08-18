"""Langfuse lifecycle and LangChain callback integration."""

# Callback 由每次 Graph 调用单独创建，避免并发会话共享 callback 的运行状态。

import asyncio
import logging
from typing import Any

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from src.config.langfuse_settings import LangfuseSettings
from src.core.runtime_secrets import RuntimeSecrets

_SENSITIVE_KEY_PARTS = ("api_key", "apikey", "authorization", "password", "secret", "token")

logger = logging.getLogger(__name__)


class LangfuseObservability:
    """Own an enabled Langfuse client and create isolated graph callbacks."""

    def __init__(self, settings: LangfuseSettings, agent_env: str, runtime_secrets: RuntimeSecrets) -> None:
        self._public_key = runtime_secrets.require_langfuse_public_key().get_secret_value()
        self._client = Langfuse(
            public_key=self._public_key,
            secret_key=runtime_secrets.require_langfuse_secret_key().get_secret_value(),
            base_url=settings.base_url,
            environment=agent_env,
            release=settings.release,
            mask=_mask_sensitive_data,
        )

    def create_callback(self) -> CallbackHandler:
        """Create one callback per graph invocation to keep LangChain run state isolated."""
        return CallbackHandler(public_key=self._public_key, update_trace=True)

    async def close(self) -> None:
        """Flush background telemetry without blocking FastAPI's event loop."""
        try:
            await asyncio.wait_for(asyncio.to_thread(self._client.shutdown), timeout=5)
        except TimeoutError:
            logger.warning("langfuse_shutdown_timed_out")
        except Exception as exc:
            logger.warning("langfuse_shutdown_failed error_type=%s", type(exc).__name__)


def _mask_sensitive_data(*, data: Any, **_: object) -> Any:
    """Recursively redact credential-like fields before Langfuse exports telemetry."""
    if isinstance(data, dict):
        return {
            key: "***"
            if any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
            else _mask_sensitive_data(data=value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_mask_sensitive_data(data=item) for item in data]
    if isinstance(data, tuple):
        return tuple(_mask_sensitive_data(data=item) for item in data)
    return data
