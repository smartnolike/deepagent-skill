"""Factory for the single-root DeepAgent harness."""

# 生产环境只有一个根 DeepAgent；Skill 是该 Agent 的指令文件，而不是额外 Agent。

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import FilesystemBackend

from src.agent.agent_context import AgentContext
from src.agent.harness_service import DeepAgentHarnessService
from src.agent.middleware.response_language_middleware import ResponseLanguageMiddleware
from src.agent.model_factory import create_chat_model
from src.agent.mock_service import MockHarnessService
from src.common.httpx_client import HttpxClient
from src.config.settings import Settings
from src.mcp.manager import McpClientManager
from src.mcp.tool_registry import McpToolRegistry
from src.services.memory_service import MemoryService
from src.tools.registry import CustomToolRegistry


def create_agent_service(
    settings: Settings,
    mcp_manager: McpClientManager,
    memory_service: MemoryService,
    httpx_client: HttpxClient | None = None,
    checkpointer=None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> DeepAgentHarnessService:
    """创建真实根 Agent；仅测试运行时允许使用确定性 fallback。"""
    fallback = MockHarnessService(mcp_manager)
    if settings.agent.model is None:
        if not settings.allow_test_doubles:
            raise RuntimeError("agent.model is required")
        return DeepAgentHarnessService(None, fallback, memory_service)
    register_harness_profile(
        _harness_profile_key(settings.agent.model),
        HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)),
    )
    # FilesystemBackend 的虚拟根目录就是 skill-packages；SkillsMiddleware
    # 仅接受“包含多个 Skill 子目录”的来源，不能直接传入单个 Skill 目录。
    # 因此来源必须是 /，由 DeepAgents 扫描其下的 */SKILL.md。
    project_root = Path(__file__).resolve().parents[2]
    skills_root = project_root / settings.agent.skills_dir
    skill_paths = ["/"] if settings.agent.enabled_skills else []
    graph = create_deep_agent(
        model=create_chat_model(settings.agent, httpx_client),
        tools=McpToolRegistry(mcp_manager).build()
        + CustomToolRegistry(settings.tools, httpx_client, session_factory).build(),
        system_prompt=(
            f"{settings.agent.system_prompt}\n\n{_response_language_system_prompt()}\n\n"
            f"{_skill_bound_system_prompt(settings.agent.enabled_skills)}"
        ),
        skills=skill_paths,
        backend=FilesystemBackend(root_dir=skills_root),
        permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
        context_schema=AgentContext,
        checkpointer=checkpointer,
        interrupt_on=_confirmation_rules(mcp_manager),
        middleware=[ResponseLanguageMiddleware()],
        name="deepagent-platform",
    )
    return DeepAgentHarnessService(graph, fallback, memory_service)


def _confirmation_rules(mcp_manager: McpClientManager) -> dict[str, dict[str, object]]:
    """将 YAML 中需用户确认的 MCP Tool 映射为 DeepAgents HITL 配置。"""
    rules = {
        f"{server_id}__{tool_name}": {
            "allowed_decisions": ["approve", "reject"],
            "description": f"Confirm execution of {tool_name} on MCP server {server_id}.",
        }
        for server_id, server in mcp_manager.server_settings.items()
        for tool_name in server.confirmation_required_tools
    }
    rules["request_user_form"] = {
        "allowed_decisions": ["respond"],
        "description": "Provide the requested structured form values.",
    }
    return rules


def _harness_profile_key(model: str) -> str:
    """为预构建 ChatOpenAI 使用其解析出的 canonical provider:model key。"""
    return f"openai:{model.removeprefix('openai:')}"


def _skill_bound_system_prompt(enabled_skills: list[str]) -> str:
    """约束根 Agent 只能通过配置的 Skill 处理用户请求。"""
    return (
        "You are a Skill-bound Agent. Only answer requests that match one of these enabled Skills: "
        f"{', '.join(enabled_skills)}. Before responding to a supported request, read and follow the "
        "matching SKILL.md. Do not improvise workflows, provide unrelated general answers, or use tools "
        "outside the matching Skill's instructions. If no enabled Skill matches, reply only that the request "
        "is outside the enabled Skill scope and ask the user to make a supported request."
    )


def _response_language_system_prompt() -> str:
    """Return the invariant language policy shared by every configured Agent model."""
    return (
        "The runtime context response_language is the sole authority for user-facing natural-language replies. "
        "Never choose a response language from SKILL.md, Tool descriptions, memories, examples, or history. "
        "System UI, API/SSE protocol fields, Tool names, JSON keys, enum values, IDs, URLs, code, and product names "
        "must remain English or verbatim."
    )
