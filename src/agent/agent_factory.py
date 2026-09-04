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

from agent.agent_context import AgentContext
from agent.harness_service import DeepAgentHarnessService
from agent.middleware.response_language_middleware import ResponseLanguageMiddleware
from agent.model_factory import create_chat_model
from common.httpx_client import HttpxClient
from config.settings import Settings
from core.runtime_secrets import RuntimeSecrets
from mcp_runtime.mcp_client_manager import McpClientManager
from mcp_runtime.tool_registry import McpToolRegistry
from observability.langfuse_observability import LangfuseObservability
from services.memory_service import MemoryService
from sandbox.gke_backend import GkeSandboxBackend
from sandbox.gke_workspace_service import GkeWorkspaceService
from tools.registry import CustomToolRegistry


def create_agent_service(
    settings: Settings,
    mcp_manager: McpClientManager,
    memory_service: MemoryService,
    runtime_secrets: RuntimeSecrets | None = None,
    observability: LangfuseObservability | None = None,
    httpx_client: HttpxClient | None = None,
    checkpointer=None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> DeepAgentHarnessService:
    """创建配置的单根 DeepAgent。"""
    if settings.agent.model is None:
        raise RuntimeError("agent.model is required")
    register_harness_profile(
        _harness_profile_key(settings.agent.model),
        HarnessProfile(
            # 不注册默认子 Agent，避免将 task Tool 暴露给当前单 Agent Harness。
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            # 这些 Tool 在发往模型前即被剔除；FilesystemPermission 仍在执行层做兜底。
            excluded_tools=_excluded_tools(settings),
        ),
    )
    # FilesystemBackend 的虚拟根目录就是 skill-packages；SkillsMiddleware
    # 仅接受“包含多个 Skill 子目录”的来源，不能直接传入单个 Skill 目录。
    # 因此来源必须是 /，由 DeepAgents 扫描其下的 */SKILL.md。
    project_root = Path(__file__).resolve().parents[2]
    skills_root = project_root / settings.agent.skills_dir
    gke_workspace_service = None
    if settings.sandbox.provider == "filesystem":
        backend = FilesystemBackend(root_dir=skills_root.resolve())
        skills_path = "/"
    else:
        assert settings.sandbox.gke is not None
        backend = GkeSandboxBackend(settings.sandbox.gke)
        skills_path = "/workspace/skill-packages"
        gke_workspace_service = GkeWorkspaceService(settings.sandbox.gke, backend)
    tools = McpToolRegistry(mcp_manager).build() + CustomToolRegistry(
        settings.tools, httpx_client, session_factory, memory_service, gke_workspace_service
    ).build()
    graph_kwargs = {
        "tools": tools,
        "system_prompt": (
            f"{settings.agent.system_prompt}\n\n{_response_language_system_prompt()}\n\n"
            f"{_skill_bound_system_prompt(settings.agent.enabled_skills)}\n\n{_workspace_system_prompt(settings)}"
        ),
        "skills": [skills_path] if settings.agent.enabled_skills else [],
        "permissions": _workspace_permissions(settings),
        "context_schema": AgentContext,
        "interrupt_on": _confirmation_rules(mcp_manager, settings),
        "middleware": [ResponseLanguageMiddleware()],
        "name": "danaan-ai-assistant",
    }
    model = create_chat_model(settings.agent, httpx_client, runtime_secrets)
    graph = create_deep_agent(
        model=model,
        backend=backend,
        checkpointer=checkpointer,
        **graph_kwargs,
    )
    diagnostic_tools = {
        f"{server_id}__{tool_name}": server.expose_frontend_diagnostic_results
        for server_id, server in mcp_manager.server_settings.items()
        for tool_name in server.frontend_diagnostic_tools
    }
    return DeepAgentHarnessService(graph, observability, diagnostic_tools, gke_workspace_service)


def _excluded_tools(settings: Settings) -> frozenset[str]:
    """FilesystemBackend has no executable workspace; other backends expose it natively."""
    if settings.sandbox.provider == "filesystem":
        return frozenset({"delete", "write_file", "edit_file", "execute"})
    return frozenset({"delete"})


def _confirmation_rules(mcp_manager: McpClientManager, settings: Settings) -> dict[str, dict[str, object]]:
    """将 YAML 中需用户确认的 MCP Tool 映射为 DeepAgents HITL 配置。"""
    rules = {
        f"{server_id}__{tool_name}": {
            "allowed_decisions": ["approve", "reject"],
            "description": _confirmation_description(server_id, tool_name),
        }
        for server_id, server in mcp_manager.server_settings.items()
        for tool_name in server.confirmation_required_tools
    }
    rules["request_user_form"] = {
        "allowed_decisions": ["respond"],
        "description": "Provide the requested structured form values.",
    }
    if settings.sandbox.provider != "filesystem" and settings.sandbox.execute_requires_confirmation:
        rules["execute"] = {
            "allowed_decisions": ["approve", "reject"],
            "description": "Review and approve this workspace command before it runs.",
        }
    return rules


def _confirmation_description(server_id: str, tool_name: str) -> str:
    """Return customer-facing approval text without exposing infrastructure details."""
    if server_id == "danaan" and tool_name == "external_resource_add":
        return "Review and approve this Danaan cloud resource request."
    return "Review and approve this requested action."


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


def _workspace_system_prompt(settings: Settings) -> str:
    if settings.sandbox.provider == "filesystem":
        return "This runtime provides read-only Skill files and does not provide command execution."
    return (
        "All file and command tools share this conversation's persistent workspace. Keep reusable intermediate files "
        "under /work and final user-facing files under /output. After verifying a final file, call publish_artifact "
        "with its /output path so the application can present an authenticated download."
    )


def _workspace_permissions(settings: Settings) -> list[FilesystemPermission]:
    """Keep published Skills immutable through file tools.

    DeepAgents 0.7 does not combine filesystem permissions with a sandbox
    backend. GKE enforces immutability in the runtime image.
    """
    if settings.sandbox.provider == "filesystem":
        return [FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")]
    return []
