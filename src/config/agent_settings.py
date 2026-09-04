"""DeepAgent harness configuration model."""

# Agent 配置只描述模型与启用的 Skill，不承载业务流程判断。

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator

from .token_auth_settings import TokenAuthSettings


class AgentSettings(BaseModel):
    """Model and Skill selection settings for the single root DeepAgent."""

    provider: Literal["internal", "openai", "openai_compatible"] = "internal"
    model: str | None = None
    base_url: str | None = None
    api_key: SecretStr | None = None
    token_auth: TokenAuthSettings | None = None
    skills_dir: str = "skill-packages"
    enabled_skills: list[str] = Field(default_factory=list)
    system_prompt: str = "You are the Danaan AI Assistant. Use applicable skills and tools."

    @model_validator(mode="after")
    def validate_model_auth(self) -> "AgentSettings":
        """拒绝内部动态 Token 与外部固定 Key 的混合配置。"""
        if self.token_auth is not None and self.base_url is None:
            raise ValueError("agent.base_url is required when agent.token_auth is configured")
        if self.provider == "internal" and self.api_key is not None:
            raise ValueError("agent.api_key is only supported when agent.provider is openai or openai_compatible")
        if self.provider in {"openai", "openai_compatible"} and self.token_auth is not None:
            raise ValueError("agent.token_auth is only supported when agent.provider is internal")
        if self.provider == "openai" and self.base_url is not None:
            raise ValueError("agent.base_url is not supported when agent.provider is openai")
        if self.provider == "openai_compatible" and self.base_url is None:
            raise ValueError("agent.base_url is required when agent.provider is openai_compatible")
        return self
