"""启动期解析后仅驻留内存的运行时机密。"""

# Settings 仅保存 Secret 引用；此对象只在进程内保存已解析的 SecretStr，避免回写配置模型。

from pydantic import SecretStr


class RuntimeSecrets:
    """Hold startup-resolved secrets required by long-lived application services."""

    def __init__(
        self,
        translator_service_account_password: SecretStr | None = None,
        langfuse_public_key: SecretStr | None = None,
        langfuse_secret_key: SecretStr | None = None,
        mcp_secrets: dict[str, SecretStr] | None = None,
    ) -> None:
        self._translator_service_account_password = translator_service_account_password
        self._langfuse_public_key = langfuse_public_key
        self._langfuse_secret_key = langfuse_secret_key
        self._mcp_secrets = dict(mcp_secrets or {})

    def require_translator_service_account_password(self) -> SecretStr:
        """Return the injected translator password or fail without revealing secret material."""
        if self._translator_service_account_password is None:
            raise RuntimeError("TRANSLATOR_SERVICE_ACCOUNT_PASSWORD_UNAVAILABLE")
        return self._translator_service_account_password

    def require_langfuse_public_key(self) -> SecretStr:
        """Return the startup-resolved Langfuse public key without exposing it in errors."""
        if self._langfuse_public_key is None:
            raise RuntimeError("LANGFUSE_PUBLIC_KEY_UNAVAILABLE")
        return self._langfuse_public_key

    def require_langfuse_secret_key(self) -> SecretStr:
        """Return the startup-resolved Langfuse secret key without exposing it in errors."""
        if self._langfuse_secret_key is None:
            raise RuntimeError("LANGFUSE_SECRET_KEY_UNAVAILABLE")
        return self._langfuse_secret_key

    def require_mcp_secret(self, secret_version: str) -> SecretStr:
        """Return a startup-resolved MCP secret without exposing its value."""
        secret = self._mcp_secrets.get(secret_version)
        if secret is None:
            raise RuntimeError("MCP_SECRET_UNAVAILABLE")
        return secret
