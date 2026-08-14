"""Startup resolution for runtime secrets referenced by settings."""

# 不在每次 Agent 请求或 Token 刷新中访问 Secret Manager，降低延迟与 API 调用量。

from src.config.settings import Settings
from src.core.google_secret_manager import GoogleSecretManager
from src.core.runtime_secrets import RuntimeSecrets


async def resolve_runtime_secrets(settings: Settings) -> RuntimeSecrets:
    """Resolve configured startup secrets once and return their in-memory container."""
    token_auth = settings.agent.token_auth
    if token_auth is None:
        return RuntimeSecrets()
    if token_auth.service_account_password is not None:
        return RuntimeSecrets(token_auth.service_account_password)

    secret_version_name = token_auth.service_account_password_secret
    if secret_version_name is None:
        raise RuntimeError("TRANSLATOR_SERVICE_ACCOUNT_PASSWORD_UNAVAILABLE")
    manager = GoogleSecretManager()
    try:
        password = await manager.access_secret(secret_version_name)
    finally:
        await manager.close()
    return RuntimeSecrets(password)
