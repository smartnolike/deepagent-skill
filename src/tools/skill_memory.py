"""受控的 Skill 长期记忆读取 Tool。"""

# Tool 仅使用 runtime 中的 staff_id，模型不能传入或伪造其他员工身份。

import json
import logging

from langchain.tools import ToolRuntime
from langchain_core.tools import StructuredTool

from src.agent.agent_context import AgentContext
from src.services.danaan_memory import DANAAN_BASE_CONTEXT_KEY
from src.services.memory_service import MemoryService

logger = logging.getLogger(__name__)

ALLOWED_SKILL_MEMORY_KEYS = frozenset({DANAAN_BASE_CONTEXT_KEY})


def create_get_skill_memory_tool(memory_service: MemoryService) -> StructuredTool:
    """创建只能读取白名单记忆 key 的运行时 Tool。"""

    async def get_skill_memory(key: str, runtime: ToolRuntime[AgentContext]) -> str:
        """Read one allowlisted memory value for the current staff member only."""
        if key not in ALLOWED_SKILL_MEMORY_KEYS:
            logger.warning("skill_memory_access_denied key=%s", key)
            return json.dumps({"found": False, "key": key, "error": "memory key is not allowed"})
        staff_id = runtime.context["staff_id"]
        value = await memory_service.get(staff_id, key)
        logger.info("skill_memory_read staff_id=%s memory_key=%s found=%s", staff_id, key, value is not None)
        return json.dumps({"found": value is not None, "key": key, "value": value}, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=get_skill_memory,
        name="get_skill_memory",
        description="Read one approved Skill memory key for the current staff member. The staff identity is injected at runtime.",
    )
