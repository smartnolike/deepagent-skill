"""Google Secret Manager startup-only client."""

# Secret payload 只在内存中以 SecretStr 保存，日志仅记录 resource name 与错误类型。

import logging
from inspect import isawaitable

from google.cloud import secretmanager
from pydantic import SecretStr

logger = logging.getLogger(__name__)


class GoogleSecretManager:
    """Read configured secret versions through ADC or GKE Workload Identity."""

    def __init__(self) -> None:
        self._client = secretmanager.SecretManagerServiceAsyncClient()

    async def access_secret(self, secret_version_name: str) -> SecretStr:
        """Read one non-empty UTF-8 secret version without logging its payload."""
        try:
            response = await self._client.access_secret_version(request={"name": secret_version_name})
            value = response.payload.data.decode("utf-8")
        except Exception as exc:
            logger.exception(
                "secret_manager_access_failed",
                extra={"fields": {"secret_version": secret_version_name, "error_type": type(exc).__name__}},
            )
            raise RuntimeError("STARTUP_SECRET_UNAVAILABLE") from exc
        if not value:
            logger.warning("secret_manager_access_empty secret_version=%s", secret_version_name)
            raise RuntimeError("STARTUP_SECRET_UNAVAILABLE")
        logger.info("secret_manager_accessed secret_version=%s", secret_version_name)
        return SecretStr(value)

    async def close(self) -> None:
        """Close the asynchronous gRPC client after startup resolution."""
        result = self._client.transport.close()
        if isawaitable(result):
            await result
