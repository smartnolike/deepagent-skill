"""OpenAI-compatible model dynamic-token configuration."""

# 令牌服务凭据使用 SecretStr，避免被配置日志或异常字符串意外输出。

from pydantic import BaseModel, Field, SecretStr


class TokenAuthSettings(BaseModel):
    """Credentials and response mapping for the translator token endpoint."""

    translator_url: str
    service_account: str
    service_account_password: SecretStr
    refresh_before_expiry_seconds: int = Field(default=5, ge=0)
    request_timeout_seconds: float = Field(default=3.0, gt=0)
    token_field: str = "access_token"
    expires_in_field: str = "expires_in"
