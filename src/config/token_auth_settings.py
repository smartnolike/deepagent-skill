"""OpenAI-compatible model dynamic-token configuration."""

# 令牌服务凭据使用 SecretStr，避免被配置日志或异常字符串意外输出。

from pydantic import BaseModel, Field, SecretStr, model_validator


class TokenAuthSettings(BaseModel):
    """Credentials and response mapping for the translator token endpoint."""

    translator_url: str
    service_account_name: str
    service_account_password: SecretStr | None = None
    service_account_password_secret: str | None = None
    refresh_before_expiry_seconds: int = Field(default=5, ge=0)
    token_ttl_seconds: int = Field(default=30, gt=0)
    request_timeout_seconds: float = Field(default=3.0, gt=0)
    token_field: str = "issued_token"

    @model_validator(mode="after")
    def validate_password_source(self) -> "TokenAuthSettings":
        """要求明文密码与 Secret Manager 引用二选一。"""
        has_password = self.service_account_password is not None
        has_secret_reference = self.service_account_password_secret is not None
        if has_password == has_secret_reference:
            raise ValueError(
                "exactly one of service_account_password or service_account_password_secret is required"
            )
        if self.refresh_before_expiry_seconds >= self.token_ttl_seconds:
            raise ValueError("refresh_before_expiry_seconds must be less than token_ttl_seconds")
        return self
