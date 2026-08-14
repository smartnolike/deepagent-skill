"""启动期解析后仅驻留内存的运行时机密。"""

# Settings 仅保存 Secret 引用；此对象只在进程内保存已解析的 SecretStr，避免回写配置模型。

from pydantic import SecretStr


class RuntimeSecrets:
    """Hold startup-resolved secrets required by long-lived application services."""

    def __init__(self, translator_service_account_password: SecretStr | None = None) -> None:
        self._translator_service_account_password = translator_service_account_password

    def require_translator_service_account_password(self) -> SecretStr:
        """Return the injected translator password or fail without revealing secret material."""
        if self._translator_service_account_password is None:
            raise RuntimeError("TRANSLATOR_SERVICE_ACCOUNT_PASSWORD_UNAVAILABLE")
        return self._translator_service_account_password
