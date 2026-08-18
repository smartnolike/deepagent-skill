"""DeepAgent harness factory tests."""

# 未配置真实模型时必须保持可运行的 Mock harness，便于本地回归测试。

from src.agent.harness_service import DeepAgentHarnessService
from src.agent.agent_factory import (
    _harness_profile_key,
    _response_language_system_prompt,
    _skill_bound_system_prompt,
    create_agent_service,
)
from src.agent.middleware.response_language_middleware import response_language_instruction
from src.config.settings import Settings
from src.mcp.manager import McpClientManager
from src.services.memory_service import MemoryService
from langgraph.store.memory import InMemoryStore


def test_factory_uses_mock_harness_without_model() -> None:
    settings = Settings.model_validate(
        {
            "agent_env": "local",
            "allow_test_doubles": True,
            "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
            "api_auth_token": "x",
            "mcp_servers": {"ticketing": {"transport": "mock", "tools": []}},
        }
    )
    assert isinstance(
        create_agent_service(settings, McpClientManager(settings), MemoryService(InMemoryStore())),
        DeepAgentHarnessService,
    )


def test_harness_profile_key_matches_prebuilt_chat_openai_provider() -> None:
    assert _harness_profile_key("gpt-5.6-luna") == "openai:gpt-5.6-luna"
    assert _harness_profile_key("openai:gpt-5.6-luna") == "openai:gpt-5.6-luna"


def test_skill_bound_prompt_limits_the_agent_to_enabled_skills() -> None:
    prompt = _skill_bound_system_prompt(["ticket-request"])
    assert "ticket-request" in prompt
    assert "Do not improvise workflows" in prompt
    assert "outside the enabled Skill scope" in prompt


def test_response_language_prompts_do_not_follow_skill_document_language() -> None:
    assert "sole authority" in _response_language_system_prompt()
    assert "Use English" in response_language_instruction("en")
    assert "Use Chinese" in response_language_instruction("zh-CN")
    assert "Skill files" in response_language_instruction("en")
