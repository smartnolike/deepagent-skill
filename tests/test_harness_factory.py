"""DeepAgent harness factory tests."""

# 未配置模型时工厂必须拒绝启动；生产环境不提供 fallback harness。

import pytest

from agent.agent_factory import (
    _confirmation_description,
    _confirmation_rules,
    _excluded_tools,
    _harness_profile_key,
    _response_language_system_prompt,
    _skill_bound_system_prompt,
    create_agent_service,
)
from agent.middleware.response_language_middleware import response_language_instruction
from config.settings import Settings
from mcp_runtime.mcp_client_manager import McpClientManager
from services.memory_service import MemoryService
from langgraph.store.memory import InMemoryStore
from sandbox.backend_factory import create_gke_sandbox_manager


def test_factory_requires_a_configured_model() -> None:
    settings = Settings.model_validate(
        {
            "agent_env": "local",
            "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
            "api_auth_token": "x",
            "mcp_servers": {},
        }
    )
    with pytest.raises(RuntimeError, match="agent.model is required"):
        create_agent_service(settings, McpClientManager(settings), MemoryService(InMemoryStore()))


def test_harness_profile_key_matches_prebuilt_chat_openai_provider() -> None:
    assert _harness_profile_key("gpt-5.6-luna") == "openai:gpt-5.6-luna"
    assert _harness_profile_key("openai:gpt-5.6-luna") == "openai:gpt-5.6-luna"


def test_confirmation_description_hides_mcp_implementation_details() -> None:
    assert _confirmation_description("danaan", "external_resource_add") == (
        "Review and approve this Danaan cloud resource request."
    )
    assert _confirmation_description("danaan", "search") == "Review and approve this requested action."


def test_local_shell_exposes_execute_with_confirmation() -> None:
    settings = Settings.model_validate(
        {
            "agent_env": "local",
            "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
            "api_auth_token": "x",
            "mcp_servers": {},
            "sandbox": {"provider": "local_shell", "allow_agent_shell": True},
        }
    )

    assert "execute" not in _excluded_tools(settings)
    assert _confirmation_rules(McpClientManager(settings), settings)["execute"]["allowed_decisions"] == [
        "approve",
        "reject",
    ]


def test_gke_agent_uses_packaged_kubernetes_sandbox_manager() -> None:
    settings = Settings.model_validate(
        {
            "agent_env": "dev",
            "database": {"host": "x", "name": "x", "user": "x"},
            "api_auth_token": "x",
            "mcp_servers": {},
            "sandbox": {
                "provider": "gke_agent",
                "gke": {
                    "namespace": "agent-sandbox",
                    "template_name": "deepagent-runtime",
                    "warm_pool_name": "deepagent-runtime-pool",
                    "router_url": "http://sandbox-router-svc.agent-sandbox.svc.cluster.local:8080",
                },
            },
        }
    )

    manager = create_gke_sandbox_manager(settings.sandbox)
    provider_config = manager._provider._config
    assert provider_config.connection_mode == "direct"
    assert provider_config.api_url == settings.sandbox.gke.router_url
    assert provider_config.server_port == 38_087
    assert "execute" not in _excluded_tools(settings)
    assert _confirmation_rules(McpClientManager(settings), settings)["execute"]["description"].endswith(
        "the GKE sandbox."
    )


def test_kind_uses_packaged_kubernetes_tunnel() -> None:
    settings = Settings.model_validate(
        {
            "agent_env": "local",
            "database": {"host": "x", "name": "x", "user": "x", "password": "x"},
            "api_auth_token": "x",
            "mcp_servers": {},
            "sandbox": {
                "provider": "gke_agent",
                "gke": {
                    "namespace": "agent-sandbox",
                    "template_name": "deepagent-runtime",
                    "warm_pool_name": "deepagent-runtime-pool",
                    "connection_mode": "tunnel",
                },
            },
        }
    )

    manager = create_gke_sandbox_manager(settings.sandbox)
    provider_config = manager._provider._config
    assert provider_config.connection_mode == "tunnel"
    assert provider_config.api_url is None


def test_skill_bound_prompt_limits_the_agent_to_enabled_skills() -> None:
    prompt = _skill_bound_system_prompt(["danaan-cloud-resource"])
    assert "danaan-cloud-resource" in prompt
    assert "Do not improvise workflows" in prompt
    assert "outside the enabled Skill scope" in prompt


def test_response_language_prompts_do_not_follow_skill_document_language() -> None:
    assert "sole authority" in _response_language_system_prompt()
    assert "Use English" in response_language_instruction("en")
    assert "Use Chinese" in response_language_instruction("zh-CN")
    assert "Skill files" in response_language_instruction("en")
