"""Startup resolution for runtime secrets referenced by settings."""

# 不在每次 Agent 请求或 Token 刷新中访问 Secret Manager，降低延迟与 API 调用量。

from config.settings import Settings
from core.google_secret_manager import GoogleSecretManager
from core.runtime_secrets import RuntimeSecrets


async def resolve_runtime_secrets(settings: Settings) -> RuntimeSecrets:
    """Resolve configured startup secrets once and return their in-memory container."""
    token_auth = settings.agent.token_auth
    translator_password = token_auth.service_account_password if token_auth is not None else None
    langfuse_public_key = settings.langfuse.public_key
    langfuse_secret_key = settings.langfuse.secret_key
    secret_version_names = {
        "translator": token_auth.service_account_password_secret if token_auth is not None else None,
        "langfuse_public": settings.langfuse.public_key_secret,
        "langfuse_secret": settings.langfuse.secret_key_secret,
    }
    mcp_secret_versions = list(
        dict.fromkeys(
            credential.secret_version
            for server in settings.mcp_servers.values()
            for credential in server.credential_headers.values()
            if credential.source == "gcp_secret_manager" and credential.secret_version is not None
        )
    )
    if not any(secret_version_names.values()) and not mcp_secret_versions:
        return RuntimeSecrets(translator_password, langfuse_public_key, langfuse_secret_key)

    manager = GoogleSecretManager()
    mcp_secrets = {}
    try:
        if secret_version_names["translator"] is not None:
            translator_password = await manager.access_secret(secret_version_names["translator"])
        if secret_version_names["langfuse_public"] is not None:
            langfuse_public_key = await manager.access_secret(secret_version_names["langfuse_public"])
        if secret_version_names["langfuse_secret"] is not None:
            langfuse_secret_key = await manager.access_secret(secret_version_names["langfuse_secret"])
        for secret_version in mcp_secret_versions:
            mcp_secrets[secret_version] = await manager.access_secret(secret_version)
    finally:
        await manager.close()
    return RuntimeSecrets(translator_password, langfuse_public_key, langfuse_secret_key, mcp_secrets)
