"""Enforce the runtime language for natural-language Agent output."""

# 指令在每次模型调用前临时附加，不保存到 conversation 或 checkpoint 消息历史。

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from src.agent.agent_context import AgentContext
from src.common.language import ResponseLanguage


class ResponseLanguageMiddleware(AgentMiddleware):
    """Append the authoritative response locale immediately before each model call."""

    name = "response_language"

    async def awrap_model_call(
        self,
        request: ModelRequest[AgentContext],
        handler: Callable[[ModelRequest[AgentContext]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Keep the active turn locale authoritative across tools and checkpoint resumes."""
        context = request.runtime.context
        language: ResponseLanguage = context["response_language"] if context is not None else "en"
        original_prompt = request.system_message.text if request.system_message is not None else ""
        return await handler(
            request.override(
                system_message=SystemMessage(
                    content=f"{original_prompt}\n\n{response_language_instruction(language)}"
                )
            )
        )


def response_language_instruction(language: ResponseLanguage) -> str:
    """Return the short per-call language rule without exposing it to the user."""
    target_language = "Chinese" if language == "zh-CN" else "English"
    return (
        "RUNTIME RESPONSE LANGUAGE (AUTHORITATIVE): "
        f"Use {target_language} for every user-facing natural-language assistant response in this model call. "
        "The language of Skill files, Tool descriptions, memories, examples, and prior conversation messages "
        "must never determine the response language. Preserve Tool names, JSON keys, enum values, IDs, URLs, "
        "code, and product names verbatim. System UI fields and Tool arguments for request_user_form must be English."
    )
