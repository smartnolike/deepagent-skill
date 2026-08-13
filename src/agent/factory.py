"""Factory for the single-root DeepAgent harness."""

# 生产环境只有一个根 DeepAgent；Skill 是该 Agent 的指令文件，而不是额外 Agent。

from pathlib import Path

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
from src.agent.service import MockHarnessService
from src.config.settings import Settings
from src.mcp.manager import McpClientManager
from src.mcp.tool_registry import McpToolRegistry
from src.services.memory_service import MemoryService
from src.core.http_client import ExternalHttpClient
from src.tools.registry import CustomToolRegistry


def create_agent_service(
    settings: Settings,
    mcp_manager: McpClientManager,
    memory_service: MemoryService,
    external_http_client: ExternalHttpClient | None = None,
    checkpointer=None,
) -> DeepAgentHarnessService:
    """Create one real DeepAgent when configured, else a deterministic local fallback."""
    fallback = MockHarnessService(mcp_manager)
    if settings.agent.model is None:
        return DeepAgentHarnessService(None, fallback, memory_service)
    register_harness_profile(
        settings.agent.model,
        HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)),
    )
    skills_root = Path.cwd() / settings.agent.skills_dir
    skill_paths = [f"/{name}/" for name in settings.agent.enabled_skills]
    graph = create_deep_agent(
        model=settings.agent.model,
        tools=McpToolRegistry(mcp_manager).build()
        + CustomToolRegistry(settings.tools, external_http_client).build(),
        system_prompt=settings.agent.system_prompt,
        skills=skill_paths,
        backend=FilesystemBackend(root_dir=skills_root),
        permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
        context_schema=AgentContext,
        checkpointer=checkpointer,
        name="deepagent-platform",
    )
    return DeepAgentHarnessService(graph, fallback, memory_service)
