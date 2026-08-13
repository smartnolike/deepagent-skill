"""DeepAgent harness configuration model."""

# Agent 配置只描述模型与启用的 Skill，不承载业务流程判断。

from pydantic import BaseModel, Field


class AgentSettings(BaseModel):
    """Model and Skill selection settings for the single root DeepAgent."""

    model: str | None = None
    skills_dir: str = "src/skills"
    enabled_skills: list[str] = Field(default_factory=list)
    system_prompt: str = "You are the DeepAgent Platform assistant. Use applicable skills and tools."
